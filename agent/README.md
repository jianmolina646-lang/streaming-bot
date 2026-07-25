# Jheliz Agent para Windows

Agente local privado que recibirá trabajos autorizados desde JhelizTV y
ejecutará acciones en un navegador visible. La primera versión está bloqueada
en modo de simulación: valida trabajos y devuelve resultados, pero no inicia
sesión ni modifica cuentas de streaming.

## Principios de seguridad

- Solo se comunica por HTTPS.
- Usa un token individual de emparejamiento.
- Recibe referencias opacas; no contraseñas en la cola.
- Solo acepta `netflix/create_profile`.
- Valida nombre y PIN antes de ejecutar.
- El modo real permanece bloqueado hasta completar las pruebas de aislamiento.
- Nunca imprime contraseñas, PIN completos, cookies ni códigos de acceso.

## Preparación en Windows

```powershell
cd agent
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
Copy-Item .env.example .env
```

Las variables se cargarán desde el proceso o desde el futuro instalador. No
subas `.env`, perfiles de navegador ni tokens al repositorio.

## Pruebas

```powershell
$env:PYTHONPATH = "."
python -m unittest discover -s tests -v
```

## Próxima fase

1. API de emparejamiento y cola en JhelizTV.
2. Aislamiento obligatorio por ID de revendedor.
3. Relación opaca con la cuenta y correo de Mail Control.
4. Flujo de recuperación de código con ventana temporal y un solo uso.
5. Navegador visible y almacenamiento local cifrado de la sesión.
6. Prueba supervisada con una cuenta propia.
