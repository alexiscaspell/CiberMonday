# Configuración de Secrets para GitHub Actions

Este documento explica cómo configurar los secrets necesarios para que el workflow pueda crear releases automáticamente.

## 🔑 Secrets Necesarios

El workflow puede usar dos tipos de tokens:

### Opción 1: GITHUB_TOKEN (Automático - Recomendado)

GitHub proporciona automáticamente `GITHUB_TOKEN` en todos los workflows. Este token tiene permisos limitados pero suficientes para crear releases en el mismo repositorio.

**Ventajas:**
- ✅ Ya está disponible, no necesitas configurar nada
- ✅ Seguro - solo funciona en el repositorio actual
- ✅ Permisos limitados por seguridad

**Limitaciones:**
- Solo puede crear releases en el repositorio donde corre el workflow
- No puede acceder a otros repositorios

### Opción 2: PERSONAL_ACCESS_TOKEN (Personal - Más Permisos)

Si necesitas más permisos o quieres usar un token personal:

#### Paso 1: Crear Personal Access Token (PAT)

1. Ve a GitHub → **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)**
2. Haz clic en **"Generate new token (classic)"**
3. Configura:
   - **Note**: `CiberMonday Release Token`
   - **Expiration**: Elige una fecha (o "No expiration" para desarrollo)
   - **Scopes**: Marca al menos:
     - ✅ `repo` (Full control of private repositories)
     - ✅ `write:packages` (si necesitas publicar paquetes)
4. Haz clic en **"Generate token"**
5. **⚠️ IMPORTANTE**: Copia el token inmediatamente (solo se muestra una vez)

#### Paso 2: Agregar el Token como Secret

1. Ve a tu repositorio en GitHub
2. Ve a **Settings** → **Secrets and variables** → **Actions**
3. Haz clic en **"New repository secret"**
4. Configura:
   - **Name**: `PERSONAL_ACCESS_TOKEN`
   - **Secret**: Pega el token que copiaste
5. Haz clic en **"Add secret"**

#### Paso 3: Verificar Permisos del Repositorio

Si el repositorio es privado o necesitas permisos especiales:

1. Ve a **Settings** → **Actions** → **General**
2. En **"Workflow permissions"**, asegúrate de que esté configurado:
   - ✅ **Read and write permissions**
   - ✅ **Allow GitHub Actions to create and approve pull requests**

## 🔧 Configuración del Workflow

El workflow está configurado para usar ambos tokens con fallback:

```yaml
env:
  GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN || secrets.PERSONAL_ACCESS_TOKEN }}
```

Esto significa:
- Primero intenta usar `GITHUB_TOKEN` (automático)
- Si no está disponible, usa `PERSONAL_ACCESS_TOKEN` (si lo configuraste)

## ✅ Verificación

Para verificar que todo funciona:

1. Ve a **Actions** → **Build Windows Client**
2. Haz clic en **"Run workflow"**
3. Ingresa una versión (ej: `1.0.0`)
4. Ejecuta el workflow
5. Si todo está bien, verás:
   - ✅ Compilación exitosa
   - ✅ Release creado en la sección "Releases"

## 🚨 Solución de Problemas

### Error: "Resource not accessible by integration"

**Causa**: El `GITHUB_TOKEN` no tiene permisos suficientes.

**Solución**:
1. Ve a **Settings** → **Actions** → **General**
2. En **"Workflow permissions"**, selecciona **"Read and write permissions"**
3. Guarda los cambios
4. O usa un `PERSONAL_ACCESS_TOKEN` con permisos `repo`

### Error: "Bad credentials"

**Causa**: El token personal es inválido o expiró.

**Solución**:
1. Verifica que el secret `PERSONAL_ACCESS_TOKEN` esté correctamente configurado
2. Genera un nuevo token si es necesario
3. Actualiza el secret en GitHub

### Error: "Release already exists"

**Causa**: Ya existe un release con el mismo tag.

**Solución**:
- Usa una versión diferente
- O elimina el release existente antes de crear uno nuevo

## 📝 Notas de Seguridad

- ⚠️ **Nunca** compartas tus tokens públicamente
- ⚠️ **Nunca** commits tokens en el código
- ✅ Usa secrets de GitHub para almacenar tokens
- ✅ Rota los tokens periódicamente
- ✅ Usa tokens con los mínimos permisos necesarios

## 🔗 Referencias

- [GitHub Actions Secrets](https://docs.github.com/en/actions/security-guides/encrypted-secrets)
- [Personal Access Tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token)
- [Workflow Permissions](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions#permissions)
