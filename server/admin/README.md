# CiberMonday Admin (Expo)

Panel de administración único (estilo Android) para web y el host Android del servidor.

## Desarrollo

```bash
cd server/admin
npm install
npx expo start --web
```

Para apuntar a un servidor local en otro puerto, abrí el panel servido por Flask (misma origen) o usá el APK nativo con pantalla de setup.

## Build estático (Flask + Android WebView)

Desde la raíz del repo:

```bash
./scripts/build_admin.sh
```

Copia el export a:

- `server/web/static/` — servido por Flask en `/`
- `server/android/app/src/main/python/admin_static/` — servido por el HTTP embebido en Android

## Admin remoto en LAN

En el servidor web/Docker: `ADMIN_ALLOW_LAN=true` (ya en `Dockerfile.server`).

El host Android carga `http://127.0.0.1:5000/` en un WebView; no hace falta setup.
