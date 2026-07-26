"""Automatización supervisada de perfiles Netflix mediante navegador visible."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, sync_playwright

from .config import AgentConfig
from .mail_control import MailControlClient
from .models import AgentJob, JobResult, JobStatus


class NetflixFlowError(RuntimeError):
    pass


def _first_visible(page: Page, selectors: tuple[str, ...]):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.is_visible(timeout=900):
                return locator
        except PlaywrightTimeout:
            continue
    return None


class NetflixAdapter:
    """Crea un perfil únicamente tras validar cuenta, código y PIN."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.mail_control = MailControlClient(config)

    def execute(self, job: AgentJob) -> JobResult:
        if self.config.dry_run:
            return JobResult(
                status=JobStatus.SUCCEEDED,
                message="Simulación completada; no se modificó ninguna cuenta.",
                evidence={
                    "dry_run": True,
                    "service": job.service,
                    "action": job.action,
                    "profile_name": job.profile_name,
                    "pin_length": len(job.profile_pin),
                    "account_reference": job.account_reference,
                    "mail_control_ready": self.mail_control.enabled and bool(job.account_email),
                },
            )
        if not self.config.allow_real_netflix:
            return JobResult(
                status=JobStatus.NEEDS_ATTENTION,
                message="Modo real bloqueado: falta JHELIZ_AGENT_ALLOW_REAL_NETFLIX=true.",
            )
        if not self.mail_control.enabled or not job.account_email:
            return JobResult(
                status=JobStatus.NEEDS_ATTENTION,
                message="No hay una cuenta exacta de Mail Control vinculada al trabajo.",
            )
        try:
            return self._execute_real(job)
        except (NetflixFlowError, PlaywrightTimeout) as exc:
            return JobResult(
                status=JobStatus.NEEDS_ATTENTION,
                message=str(exc)[:500],
                evidence={"dry_run": False, "stage": "browser_flow"},
            )
        except Exception as exc:
            return JobResult(
                status=JobStatus.FAILED,
                message=(
                    f"Error controlado del agente: {type(exc).__name__}: "
                    f"{str(exc)[:300]}"
                ),
                evidence={"dry_run": False, "stage": "unexpected"},
            )

    def _execute_real(self, job: AgentJob) -> JobResult:
        profile_dir = str(Path(self.config.browser_profile_dir).resolve())
        diagnostics_dir = Path(profile_dir).parent / "diagnostics"
        diagnostics_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser_type = (
                playwright.chromium
                if self.config.browser in {"chromium", "chrome", "msedge"}
                else playwright.chromium
            )
            channel = self.config.browser if self.config.browser in {"chrome", "msedge"} else None
            context = browser_type.launch_persistent_context(
                profile_dir,
                channel=channel,
                headless=self.config.headless,
                viewport={"width": 1365, "height": 900},
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(10_000)
                try:
                    self._ensure_login(page, job)
                    profile_created = self._create_profile_with_pin(page, job)
                except Exception:
                    try:
                        page.screenshot(
                            path=str(diagnostics_dir / f"{job.id}.png"),
                            full_page=True,
                        )
                    except Exception:
                        pass
                    raise
                return JobResult(
                    status=JobStatus.SUCCEEDED,
                    message=f"Perfil {job.profile_name} verificado con PIN configurado.",
                    evidence={
                        "dry_run": False,
                        "profile_created": profile_created,
                        "profile_name": job.profile_name,
                        "pin_configured": True,
                        "account_reference": job.account_reference,
                    },
                )
            finally:
                context.close()

    def _ensure_login(self, page: Page, job: AgentJob) -> None:
        page.goto("https://www.netflix.com/login", wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        if "browse" in page.url.lower() or "profiles" in page.url.lower():
            return
        email = _first_visible(page, (
            'input[type="email"]',
            'input[name="userLoginId"]',
            'input[autocomplete="email"]',
        ))
        if email is None:
            page.goto("https://www.netflix.com/ManageProfiles", wait_until="domcontentloaded")
            if _first_visible(page, ('[data-uia="profile-choices-row"]', '.profiles-gate-container')):
                return
            raise NetflixFlowError("Netflix no mostró el formulario de acceso esperado.")
        email.fill(job.account_email)
        code_mode = page.get_by_text(
            re.compile(r"(sign.?in code|c[oó]digo de inicio|c[oó]digo de acceso)", re.I)
        ).first
        if code_mode.is_visible(timeout=1500):
            code_mode.click()
        requested_at = datetime.now(timezone.utc)
        submit = _first_visible(page, (
            'button[type="submit"]',
            '[data-uia="login-submit-button"]',
        ))
        if submit is None:
            raise NetflixFlowError("No se encontró el botón para solicitar el código.")
        submit.click()
        code = self.mail_control.wait_for_code(
            job,
            not_before=requested_at,
            timeout_seconds=self.config.code_wait_seconds,
        )
        if not code:
            raise NetflixFlowError("Netflix no envió un código válido dentro del tiempo esperado.")
        code_input = _first_visible(page, (
            'input[autocomplete="one-time-code"]',
            'input[name="userCode"]',
            'input[inputmode="numeric"]',
            'input[type="tel"]',
        ))
        if code_input is None:
            raise NetflixFlowError("Llegó el código, pero Netflix cambió la pantalla de verificación.")
        code_input.fill(code)
        # Netflix puede confirmar automáticamente al completar el código.
        page.wait_for_timeout(1800)
        if "login" not in page.url.lower():
            return
        submit = _first_visible(page, (
            'button[type="submit"]',
            '[data-uia="login-submit-button"]',
            '[data-uia="verify-code-button"]',
        ))
        if submit is None:
            submit_text = page.get_by_text(
                re.compile(
                    r"(sign in|log in|continue|verify|submit|"
                    r"iniciar sesi[oó]n|continuar|verificar|confirmar)",
                    re.I,
                )
            ).first
            if submit_text.is_visible(timeout=1500):
                submit = submit_text
        if submit is not None:
            try:
                submit.click(timeout=3000)
            except PlaywrightTimeout:
                # El formulario puede desaparecer mientras Netflix valida.
                pass
        else:
            # El input puede desmontarse al validar; enviar Enter a la página
            # evita depender de un elemento que Netflix acaba de reemplazar.
            try:
                page.keyboard.press("Enter")
            except PlaywrightTimeout:
                pass
        try:
            page.wait_for_url(re.compile(r"^(?!.*\/login).*$", re.I), timeout=12_000)
        except PlaywrightTimeout:
            pass
        page.wait_for_timeout(1000)
        if "login" in page.url.lower():
            error = page.locator(
                '[role="alert"], [data-uia*="error"], .ui-message-error'
            ).first
            detail = error.inner_text().strip()[:180] if error.is_visible() else ""
            raise NetflixFlowError(
                "Netflix no completó el acceso con el código."
                + (f" Mensaje: {detail}" if detail else "")
            )

    def _create_profile_with_pin(self, page: Page, job: AgentJob) -> bool:
        page.goto("https://www.netflix.com/ManageProfiles", wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        if page.get_by_text(job.profile_name, exact=True).first.is_visible(timeout=1200):
            self._set_profile_pin(page, job)
            return False
        add = page.get_by_text(
            re.compile(r"(add profile|agregar perfil|añadir perfil)", re.I)
        ).first
        if not add.is_visible(timeout=2000):
            raise NetflixFlowError("No se encontró la opción Agregar perfil.")
        add.click()
        name = _first_visible(page, (
            'input[name="name"]',
            'input[data-uia="profile-name-input"]',
            'input[type="text"]',
        ))
        if name is None:
            raise NetflixFlowError("No se encontró el campo para nombrar el perfil.")
        name.fill(job.profile_name)
        save = _first_visible(page, (
            'button[type="submit"]',
            '[data-uia="profile-save-button"]',
            'button:has-text("Save")',
            'button:has-text("Guardar")',
        ))
        if save is None:
            save_by_role = page.get_by_role(
                "button", name=re.compile(r"^(save|guardar)$", re.I)
            ).first
            if save_by_role.is_visible(timeout=1500):
                save = save_by_role
        if save is None:
            raise NetflixFlowError("No se encontró el botón para guardar el perfil.")
        save.click()
        page.wait_for_timeout(1500)
        if not page.get_by_text(job.profile_name, exact=True).first.is_visible(timeout=2500):
            raise NetflixFlowError("Netflix no confirmó la creación del perfil.")
        try:
            self._set_profile_pin(page, job)
        except Exception:
            self._rollback_profile(page, job.profile_name)
            raise
        return True

    def _set_profile_pin(self, page: Page, job: AgentJob) -> None:
        # Netflix 2026 ubica Profile Lock dentro de Manage profile and
        # preferences, no en la antigua lista general de /account.
        page.goto("https://www.netflix.com/ManageProfiles", wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        profile = page.get_by_text(job.profile_name, exact=True).first
        if not profile.is_visible(timeout=2500):
            raise NetflixFlowError(
                "El perfil fue creado, pero no apareció en Administrar perfiles."
            )
        profile.click()
        page.wait_for_timeout(1200)
        lock_label = page.get_by_text(
            re.compile(r"^(profile lock|bloqueo de perfil)$", re.I)
        ).first
        if not lock_label.is_visible(timeout=2500):
            raise NetflixFlowError("Netflix no mostró la opción Bloqueo de perfil.")
        lock_control = lock_label.locator(
            "xpath=ancestor-or-self::*[self::a or self::button or @role='button'][1]"
        )
        if lock_control.count() and lock_control.first.is_visible():
            lock_control.first.click()
        else:
            # En algunas variantes la tarjeta es un div con listener.
            lock_label.locator("xpath=..").click()
        page.wait_for_timeout(1400)
        if page.get_by_text(
            re.compile(r"^manage profile and preferences$", re.I)
        ).first.is_visible(timeout=700):
            # Segundo intento sobre el contenedor ancho de la fila.
            lock_label.locator("xpath=../..").click()
            page.wait_for_timeout(1400)

        create_lock = page.get_by_text(
            re.compile(r"(create.*profile lock|crear.*bloqueo|add.*pin|agregar.*pin)", re.I)
        ).first
        if create_lock.is_visible(timeout=1800):
            create_lock.click()

        # Algunas cuentas exigen una segunda verificación por correo.
        send_code = page.get_by_text(
            re.compile(r"(send.*code|enviar.*c[oó]digo)", re.I)
        ).first
        if send_code.is_visible(timeout=1500):
            requested_at = datetime.now(timezone.utc)
            send_code.click()
            code = self.mail_control.wait_for_code(
                job,
                not_before=requested_at,
                timeout_seconds=self.config.code_wait_seconds,
            )
            if not code:
                raise NetflixFlowError("No llegó el código para configurar el PIN.")
            verification = _first_visible(page, (
                'input[autocomplete="one-time-code"]',
                'input[name="userCode"]',
                'input[inputmode="numeric"]',
                'input[type="tel"]',
            ))
            if verification is None:
                raise NetflixFlowError("Netflix cambió la verificación de Bloqueo de perfil.")
            verification.fill(code)
            confirm = _first_visible(page, ('button[type="submit"]',))
            if confirm is None:
                raise NetflixFlowError("No se encontró Confirmar identidad.")
            confirm.click()

        pin_inputs = page.locator(
            'input[name*="pin" i], input[inputmode="numeric"][maxlength="4"]'
        )
        visible_pins = []
        for index in range(pin_inputs.count()):
            candidate = pin_inputs.nth(index)
            if candidate.is_visible():
                visible_pins.append(candidate)
        if not visible_pins:
            raise NetflixFlowError("No se encontró el campo para crear el PIN del perfil.")
        for field in visible_pins[:2]:
            field.fill(job.profile_pin)
        save_pin = page.get_by_text(
            re.compile(r"(save pin|guardar pin|save|guardar)", re.I)
        ).first
        if not save_pin.is_visible(timeout=1800):
            raise NetflixFlowError("No se encontró Guardar PIN.")
        save_pin.click()
        page.wait_for_timeout(1200)
        page.goto("https://www.netflix.com/ManageProfiles", wait_until="domcontentloaded")
        profile = page.get_by_text(job.profile_name, exact=True).first
        if not profile.is_visible(timeout=2200):
            raise NetflixFlowError("No fue posible verificar el perfil después de guardar el PIN.")

    def _rollback_profile(self, page: Page, profile_name: str) -> None:
        """Mejor esfuerzo: elimina el perfil recién creado si falló el PIN."""
        try:
            page.goto("https://www.netflix.com/ManageProfiles", wait_until="domcontentloaded")
            profile = page.get_by_text(profile_name, exact=True).first
            if not profile.is_visible(timeout=1500):
                return
            profile.click()
            delete = page.get_by_text(
                re.compile(r"(delete profile|eliminar perfil)", re.I)
            ).first
            if delete.is_visible(timeout=1500):
                delete.click()
                confirm = page.get_by_text(
                    re.compile(r"(delete profile|eliminar perfil)", re.I)
                ).last
                if confirm.is_visible(timeout=1000):
                    confirm.click()
        except Exception:
            # El resultado seguirá siendo NEEDS_ATTENTION y nunca se afirmará éxito.
            return
