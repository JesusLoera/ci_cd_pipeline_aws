# Tutorial: CI/CD con Django + GitHub Actions + AWS

Este tutorial te guía paso a paso para montar un pipeline de CI/CD completo desde cero usando AWS.
Al terminar tendrás: tests automáticos en cada PR, deploy automático a staging al mergear
a `develop`, y deploy a producción al mergear a `main`.

Es el análogo directo de `tutorial-cicd.md` (que usa DigitalOcean) pero con los servicios
equivalentes de AWS. Las Fases 1 y 2 son idénticas — solo cambia la infraestructura a partir
de la Fase 3.

---

## Equivalencias DigitalOcean → AWS

| DigitalOcean | AWS | Notas |
|---|---|---|
| Droplet (Ubuntu 24.04) | EC2 instance (Ubuntu 24.04, t3.micro) | Usuario SSH: `ubuntu` en EC2, `root` en DO |
| Managed PostgreSQL | Amazon RDS for PostgreSQL | Endpoint: `todos-db.xxxx.<region>.rds.amazonaws.com` |
| DOCR (Container Registry) | Amazon ECR (Elastic Container Registry) | URI: `<account-id>.dkr.ecr.<region>.amazonaws.com` |
| Personal Access Token | IAM User con Access Keys (GitHub Actions) + IAM Instance Profile (EC2) | Más granular con políticas IAM |
| Trusted Sources (firewall DB) | Security Groups | Controlan acceso a nivel de red entre EC2 y RDS |
| Docker login user/password | `aws ecr get-login-password` | El token de ECR dura 12h — necesita renovación |

## Diferencias técnicas clave entre DO y AWS

| Aspecto | DigitalOcean | AWS |
|---|---|---|
| Usuario SSH | `root` | `ubuntu` |
| Login al registry | `docker login` con token | `aws ecr get-login-password \| docker login` |
| Autenticación en GitHub Actions | `docker/login-action` con token | `aws-actions/configure-aws-credentials` + `aws-actions/amazon-ecr-login` |
| Credenciales en el servidor | Token guardado en el servidor | IAM Instance Profile — sin credenciales en el servidor |
| Renovación del token del registry | No necesaria (token largo) | Necesaria cada 12h (cronjob recomendado) |
| Acceso entre app y DB | Trusted Sources (UI de DO) | Security Groups (reglas de firewall por servicio) |
| Variable del registry en compose | `DOCR_REGISTRY` | `ECR_REGISTRY` |

---

## Stack

| Capa | Tecnología |
|------|-----------|
| Aplicación | Django 5.1 + Django REST Framework |
| Base de datos | PostgreSQL 18 (separada de la app) |
| Contenedores local | Docker + docker-compose |
| Contenedores producción | Docker + docker-compose (misma imagen que local) |
| Registry de imágenes | Amazon ECR (Elastic Container Registry) |
| Control de versiones | Git + GitHub |
| CI | GitHub Actions — tests + build + push imagen |
| CD | GitHub Actions → SSH → docker pull → restart |
| Servidor WSGI | Gunicorn (dentro del contenedor) |
| Archivos estáticos | WhiteNoise (dentro del contenedor, sin Nginx separado) |
| Infraestructura | 2 instancias EC2 Ubuntu + Amazon RDS PostgreSQL |

## Prerequisitos

- Python 3.12+ instalado localmente
- Docker Desktop instalado
- Git configurado
- Cuenta en GitHub
- Cuenta en AWS con método de pago
- AWS CLI instalado localmente (`brew install awscli` en macOS)

## Estrategia de ramas

```
main        → deploy automático a producción
develop     → deploy automático a staging
feature/*   → PRs hacia develop, CI corre los tests
```

La regla de oro: **nunca se hace push directo a `main` ni a `develop`**. Todo pasa por Pull Request con CI verde.

---

## Fase 1 — Estructura local con Docker

**Esta fase es idéntica al tutorial de DigitalOcean.** No hay cambios — Docker funciona
igual independientemente del proveedor de nube.

**Objetivo:** proyecto Django corriendo localmente con Docker y PostgreSQL separada.

### 1.1 Crear el proyecto

```bash
mkdir my_first_ci_cd_pipeline
cd my_first_ci_cd_pipeline
git init
git checkout -b develop   # develop es la rama principal de trabajo
```

Estructura de directorios a crear:

```
my_first_ci_cd_pipeline/
├── apps/
│   └── todos/
│       ├── migrations/
│       ├── tests/
│       ├── __init__.py
│       ├── apps.py
│       ├── models.py
│       ├── serializers.py
│       ├── urls.py
│       └── views.py
├── core/
│   ├── settings/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── local.py
│   │   └── production.py
│   ├── __init__.py
│   ├── asgi.py
│   ├── urls.py
│   └── wsgi.py
├── requirements/
│   ├── base.txt
│   ├── local.txt
│   └── production.txt
├── .env
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
└── manage.py
```

### 1.2 Requirements

`requirements/base.txt` — dependencias de producción:
```
Django==5.1.6
djangorestframework==3.15.2
psycopg2-binary==2.9.10
python-decouple==3.8
gunicorn==23.0.0
whitenoise==6.9.0
```

`requirements/local.txt` — extiende base con herramientas de dev:
```
-r base.txt

# Herramientas de desarrollo (no se instalan en producción)
ruff==0.9.9
```

`requirements/production.txt`:
```
-r base.txt
```

> **Por qué separar requirements:** `ruff` es un linter que solo necesitas en desarrollo.
> Instalarlo en producción agrega peso innecesario a la imagen de producción.

### 1.3 Settings por ambiente

El patrón es: `base.py` tiene todo lo común, cada ambiente hereda y agrega lo suyo.

`core/settings/base.py`:
```python
from pathlib import Path
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config("SECRET_KEY")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    # Local apps
    "apps.todos",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "core.urls"
WSGI_APPLICATION = "core.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("POSTGRES_DB"),
        "USER": config("POSTGRES_USER"),
        "PASSWORD": config("POSTGRES_PASSWORD"),
        "HOST": config("POSTGRES_HOST"),
        "PORT": config("POSTGRES_PORT", default="5432"),
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 10,
}
```

`core/settings/local.py`:
```python
from .base import *  # noqa

DEBUG = True
ALLOWED_HOSTS = ["*"]
```

`core/settings/production.py`:
```python
from .base import *  # noqa
from decouple import config, Csv

DEBUG = False
ALLOWED_HOSTS = config("ALLOWED_HOSTS", cast=Csv())

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # justo después de SecurityMiddleware
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Activar cuando se configure HTTPS con Certbot o ACM
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
```

### 1.4 La app de Todos

`apps/todos/apps.py`:
```python
from django.apps import AppConfig

class TodosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.todos"
    # name = "apps.todos" → label automático = "todos" → tabla = "todos_todo"
```

`apps/todos/models.py`:
```python
from django.db import models

class Todo(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title
```

`apps/todos/serializers.py`:
```python
from rest_framework import serializers
from .models import Todo

class TodoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Todo
        fields = ["id", "title", "description", "completed", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]
```

`apps/todos/views.py`:
```python
from rest_framework import viewsets
from .models import Todo
from .serializers import TodoSerializer

class TodoViewSet(viewsets.ModelViewSet):
    queryset = Todo.objects.all()
    serializer_class = TodoSerializer
```

`apps/todos/urls.py`:
```python
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TodoViewSet

router = DefaultRouter()
router.register(r"todos", TodoViewSet)

urlpatterns = [path("", include(router.urls))]
```

`core/urls.py`:
```python
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.todos.urls")),
]
```

### 1.5 Variables de entorno

`.env.example` (va a git — es documentación):
```
DJANGO_SETTINGS_MODULE=core.settings.local
SECRET_KEY=your-secret-key-here-change-in-production
POSTGRES_DB=todos_db
POSTGRES_USER=todos_user
POSTGRES_PASSWORD=todos_password
POSTGRES_HOST=db
POSTGRES_PORT=5432
```

`.env` (NO va a git — valores reales locales):
```
DJANGO_SETTINGS_MODULE=core.settings.local
SECRET_KEY=django-insecure-cambia-esto-en-produccion
POSTGRES_DB=todos_db
POSTGRES_USER=todos_user
POSTGRES_PASSWORD=todos_password
POSTGRES_HOST=db
POSTGRES_PORT=5432
```

`.gitignore` debe incluir al menos:
```
.env
__pycache__/
*.pyc
staticfiles/
.DS_Store
```

### 1.6 Docker

`Dockerfile`:
```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# IMPORTANTE: copiar TODA la carpeta requirements/, no solo local.txt
# local.txt hace "-r base.txt" → si base.txt no está, el build falla
COPY requirements/ requirements/
RUN pip install --no-cache-dir -r requirements/local.txt

COPY . .

EXPOSE 8000
```

`docker-compose.yml`:
```yaml
services:
  db:
    image: postgres:18-alpine
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "5432:5432"
    healthcheck:
      # IMPORTANTE: incluir -d ${POSTGRES_DB}
      # Sin -d, pg_isready usa el nombre de usuario como nombre de DB y falla
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 5

  web:
    build: .
    command: python manage.py runserver 0.0.0.0:8000
    volumes:
      - .:/app
    ports:
      - "8000:8000"
    env_file:
      - .env
    depends_on:
      db:
        condition: service_healthy

volumes:
  postgres_data:
```

### 1.7 Generar migraciones y levantar

```bash
# Construir y levantar el stack
docker compose up --build

# En otra terminal: generar la migración inicial
docker compose exec web python manage.py makemigrations todos

# Aplicar migraciones
docker compose exec web python manage.py migrate

# Correr los tests
docker compose exec web python manage.py test apps.todos
```

### 1.8 Tests

`apps/todos/tests/test_models.py` y `apps/todos/tests/test_api.py` — idénticos al tutorial de DigitalOcean. Ver ese documento para el código completo de los 15 tests.

### 1.9 Git inicial

```bash
git add .
git commit -m "feat: estructura inicial del proyecto con Django y Docker"

git checkout -b main
git checkout develop
```

### Errores comunes en Fase 1

| Error | Causa | Solución |
|-------|-------|----------|
| `could not open requirements file: base.txt` | Dockerfile solo copia `local.txt` pero no `base.txt` | Cambiar `COPY requirements/local.txt` a `COPY requirements/ requirements/` |
| `FATAL: database "todos_user" does not exist` | Healthcheck sin `-d` usa el nombre de usuario como DB | Agregar `-d ${POSTGRES_DB}` al comando `pg_isready` |
| `relation "todos_todo" does not exist` | Se corrieron los tests sin haber hecho `makemigrations` | Ejecutar `makemigrations todos` y luego `migrate` antes de los tests |

---

## Fase 2 — CI con GitHub Actions

**Esta fase es idéntica al tutorial de DigitalOcean.** El CI solo corre tests — no toca la infraestructura cloud.

**Objetivo:** cada push o PR ejecuta tests automáticamente en GitHub.

### 2.1 Crear el repositorio en GitHub

```bash
git remote add origin https://github.com/tu-usuario/tu-repo.git
git push origin develop
git push origin main
```

> **Tip:** Para que GitHub Actions pueda crear o modificar archivos `.github/workflows/`,
> necesitas que tu token tenga el scope `workflow`. Si recibes error al hacer push, ejecuta:
> ```bash
> gh auth refresh -s workflow
> ```

### 2.2 El workflow de CI

Crea el archivo `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  test:
    name: Linting y pruebas
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:18-alpine
        env:
          POSTGRES_DB: todos_db
          POSTGRES_USER: todos_user
          POSTGRES_PASSWORD: todos_password
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    env:
      DJANGO_SETTINGS_MODULE: core.settings.local
      SECRET_KEY: ci-secret-key-only-for-testing-not-real
      POSTGRES_DB: todos_db
      POSTGRES_USER: todos_user
      POSTGRES_PASSWORD: todos_password
      POSTGRES_HOST: localhost
      POSTGRES_PORT: 5432

    steps:
      - name: Checkout del código
        uses: actions/checkout@v4

      - name: Configurar Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"
          cache-dependency-path: requirements/local.txt

      - name: Instalar dependencias del sistema
        run: sudo apt-get install -y libpq-dev

      - name: Instalar dependencias Python
        run: pip install -r requirements/local.txt

      - name: Linting con ruff
        run: ruff check .

      - name: Verificar migraciones pendientes
        run: python manage.py makemigrations --check --dry-run

      - name: Aplicar migraciones
        run: python manage.py migrate

      - name: Correr pruebas
        run: python manage.py test apps.todos --verbosity=2
```

### 2.3 Protección de ramas en GitHub

1. Ir a **Settings → Branches → Add classic branch protection rule**
2. Branch name pattern: `main`
3. Activar: **Require a pull request before merging**
4. Activar: **Require status checks to pass before merging**
   - Buscar y seleccionar el check: `Linting y pruebas`
5. Click **Create**
6. Repetir para `develop`

### Errores comunes en Fase 2

| Error | Causa | Solución |
|-------|-------|----------|
| `refusing to allow an OAuth App to create or update workflow` | Token sin scope `workflow` | `gh auth refresh -s workflow` |
| El check no aparece en el buscador de branch protection | `main` nunca tuvo un CI run | Hacer push a main primero, esperar que corra CI, luego configurar la protección |

---

## Fase 3 — Infraestructura en AWS

**Objetivo:** dos instancias EC2 reales en la nube con base de datos RDS separada y ECR para las imágenes.

### 3.1 Región

Todo debe crearse en la **misma región AWS**. Para México/LATAM la más cercana es
`us-east-1` (N. Virginia) o `us-east-2` (Ohio). Elegir una y usarla en todos los servicios.

> **Importante:** en AWS los recursos se filtran por región en la consola.
> Si algo "no aparece", verifica que estás en la región correcta en el selector
> de la esquina superior derecha.

### 3.2 Por qué separar la base de datos del servidor

```
❌ Mal:  [EC2: app + postgres]   → si cae la instancia, pierdes datos
✅ Bien: [EC2: app] → [RDS]      → escalado y backup independientes
```

Amazon RDS incluye: backups automáticos configurables, Multi-AZ para alta disponibilidad,
actualizaciones de seguridad gestionadas y réplicas de lectura.

### 3.3 Crear el repositorio ECR (Elastic Container Registry)

El registry almacena las imágenes Docker. GitHub Actions las sube; las EC2 las bajan en cada deploy.

En AWS Console: **ECR → Create repository**

| Campo | Valor |
|-------|-------|
| Visibility | Private |
| Repository name | `todos` |
| Tag immutability | Disabled (permite reusar tags como `staging-latest`) |
| Encryption | AES-256 (por defecto) |

Después de crear el repositorio, anota el URI. Tendrá esta forma:
```
123456789012.dkr.ecr.us-east-1.amazonaws.com/todos
```

El **ECR_REGISTRY** (usado en GitHub Secrets) es la parte antes del nombre del repositorio:
```
123456789012.dkr.ecr.us-east-1.amazonaws.com
```

El **ECR_REPOSITORY** es solo el nombre del repositorio:
```
todos
```

> **Diferencia con DOCR:** en ECR no hay límite de 500 MB gratuito.
> El costo es $0.10/GB/mes. Para imágenes Django (~300 MB), son ~$0.03/mes.
> Prácticamente gratis a este volumen.

### 3.4 Crear el usuario IAM para GitHub Actions

GitHub Actions necesita credenciales para hacer push a ECR. En AWS esto se gestiona con IAM.

En AWS Console: **IAM → Users → Create user**

- Username: `github-actions-deploy`
- No habilitar acceso a la consola de AWS

Adjuntar una política inline con los permisos mínimos necesarios para push a ECR:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage"
      ],
      "Resource": "arn:aws:ecr:<region>:<account-id>:repository/todos"
    },
    {
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    }
  ]
}
```

> **Por qué `GetAuthorizationToken` necesita `*`:** esta acción obtiene un token
> de autenticación a nivel de cuenta AWS, no de repositorio específico.
> Es necesaria para hacer `docker login` en ECR y no puede restringirse por ARN.

Después de crear el usuario, generar Access Keys:
**IAM → Users → github-actions-deploy → Security credentials → Create access key**

Seleccionar "Application running outside AWS". Guardar:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

Estos se configurarán en GitHub Secrets en la Fase 4.

### 3.5 Crear el IAM Role para las instancias EC2 (pull de ECR)

Las instancias EC2 necesitan bajar imágenes de ECR. El enfoque correcto en AWS es
un **IAM Instance Profile**: un rol que el EC2 asume automáticamente y que provee
credenciales temporales rotadas por AWS — sin guardar nada en el servidor.

En AWS Console: **IAM → Roles → Create role**

| Campo | Valor |
|-------|-------|
| Trusted entity type | AWS service |
| Use case | EC2 |
| Role name | `ec2-ecr-pull-role` |

Adjuntar la política inline con solo permisos de pull:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage"
      ],
      "Resource": "*"
    }
  ]
}
```

> **Por qué solo pull y no push:** las EC2 solo necesitan descargar imágenes.
> El push lo hace GitHub Actions con el usuario IAM separado.
> Principio de mínimo privilegio.

### 3.6 Crear los Security Groups

En AWS, los Security Groups son firewalls que controlan el tráfico entre recursos.
Son el equivalente a "Trusted Sources" de DigitalOcean, pero más granulares.

Crear en **EC2 → Security Groups → Create security group**:

**Security Group de las instancias EC2 (`ec2-todos-sg`):**

| Tipo | Puerto | Fuente | Descripción |
|------|--------|--------|-------------|
| SSH | 22 | Tu IP | Acceso para administración |
| HTTP | 80 | 0.0.0.0/0 | Tráfico de la app |

**Security Group de RDS (`rds-todos-sg`):**

| Tipo | Puerto | Fuente | Descripción |
|------|--------|--------|-------------|
| PostgreSQL | 5432 | `ec2-todos-sg` | Solo las EC2 pueden conectarse |

> **Por qué referenciar el Security Group y no la IP:** si la instancia se destruye
> y se recrea, obtiene una IP diferente. Referenciar el Security Group funciona
> para cualquier instancia que lo tenga, sin importar su IP.

### 3.7 Crear Amazon RDS PostgreSQL

En AWS Console: **RDS → Create database**

| Campo | Valor |
|-------|-------|
| Engine | PostgreSQL |
| Engine Version | 18 (o la más reciente disponible) |
| Template | Free tier (para aprendizaje) |
| DB instance identifier | `todos-db` |
| Master username | `todos_user` |
| Master password | Genera una segura y guárdala |
| DB instance class | `db.t3.micro` |
| Storage | 20 GB gp2 |
| VPC | Default VPC (misma que las EC2) |
| Public access | **No** (solo accesible desde dentro del VPC) |
| VPC security group | `rds-todos-sg` |
| Initial database name | (dejar vacío — se crean manualmente después) |

> **Tiempo de creación:** RDS tarda ~5-10 minutos. Avanza con los siguientes pasos mientras espera.

> **Puerto:** Amazon RDS usa el puerto estándar PostgreSQL `5432`.
> A diferencia del Managed PostgreSQL de DigitalOcean que usa el `25060`.

Después de que RDS esté disponible, conectarte para crear las dos bases de datos:

```bash
# Necesitas Public access = Yes temporalmente, o hacerlo desde dentro del VPC
# La forma más simple es habilitar temporalmente acceso público para este paso
psql -h todos-db.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com \
     -U todos_user -d postgres

# Dentro de psql:
CREATE DATABASE todos_staging;
CREATE DATABASE todos_production;
\q
```

> **Consistencia de versiones:** usa la misma versión de PostgreSQL en RDS,
> en `docker-compose.yml` (`image: postgres:18-alpine`) y en `ci.yml`.

### 3.8 Crear las instancias EC2

**EC2 → Launch instances** — repetir para staging y producción:

| Campo | Valor |
|-------|-------|
| Name | `todos-staging` / `todos-production` |
| AMI | Ubuntu Server 24.04 LTS |
| Instance type | `t3.micro` (~$8.35/mes, 1 vCPU, 1 GB RAM) |
| Key pair | Crear nuevo: `todos-deploy-key` (RSA, formato .pem). Se descarga una sola vez — guardar seguro |
| Security group | `ec2-todos-sg` |
| IAM instance profile | `ec2-ecr-pull-role` |

> **Por qué t3.micro y no t2.micro:** t3.micro tiene CPU burstable más eficiente.
> El precio es similar pero el rendimiento bajo carga puntual (deploy, migrate) es mejor.

> **IAM Instance Profile en el lanzamiento:** si lo olvidas, puedes adjuntarlo después:
> **EC2 → Actions → Security → Modify IAM role**.

### 3.9 Conectar por SSH

El usuario SSH en Ubuntu de AWS EC2 es **`ubuntu`**, no `root` como en DigitalOcean.

```bash
# Ajustar permisos de la llave (obligatorio — SSH rechaza llaves con permisos abiertos)
chmod 400 ~/.ssh/todos-deploy-key.pem

# Conectar
ssh -i ~/.ssh/todos-deploy-key.pem ubuntu@<IP_PUBLICA_EC2>
```

### 3.10 Preparar las instancias EC2

Ejecutar en **cada** instancia (conectado por SSH):

```bash
# Actualizar el sistema
sudo apt-get update && sudo apt-get upgrade -y

# Instalar Docker
curl -fsSL https://get.docker.com | sh

# Agregar el usuario ubuntu al grupo docker (para no necesitar sudo)
sudo usermod -aG docker ubuntu

# Instalar AWS CLI (necesario para renovar el token de ECR cada 12h)
sudo apt-get install -y awscli

# Cerrar sesión para que el grupo docker tome efecto
exit
```

Volver a conectar y verificar:
```bash
ssh -i ~/.ssh/todos-deploy-key.pem ubuntu@<IP_EC2>
docker --version
docker compose version
aws --version
```

Crear el directorio de la app:
```bash
sudo mkdir -p /opt/todos
sudo chown ubuntu:ubuntu /opt/todos
```

Verificar que el IAM Instance Profile funciona (debe ejecutarse sin configurar credenciales):
```bash
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  123456789012.dkr.ecr.us-east-1.amazonaws.com
```

Si el comando funciona, el Instance Profile está correctamente configurado.

Crear el archivo `.env` en el servidor con los datos reales:
```bash
cat > /opt/todos/.env << 'EOF'
DJANGO_SETTINGS_MODULE=core.settings.production
SECRET_KEY=<genera-una-key-aleatoria-segura>
POSTGRES_DB=todos_staging
POSTGRES_USER=todos_user
POSTGRES_PASSWORD=<password-de-rds>
POSTGRES_HOST=todos-db.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com
POSTGRES_PORT=5432
ALLOWED_HOSTS=<ip-publica-de-esta-ec2>
EOF
```

> **Cómo obtener el endpoint de RDS:** en AWS Console → RDS → tu instancia →
> Connectivity & security → Endpoint.
> Tendrá la forma `todos-db.xxxxxxxxxxxx.us-east-1.rds.amazonaws.com`.

### 3.11 Configurar renovación automática del token de ECR

El token de ECR dura **12 horas**. Hay que renovarlo periódicamente para que los
deploys automáticos puedan hacer pull de imágenes sin fallar.

Agregar un cronjob en **cada instancia EC2**:

```bash
crontab -e

# Agregar esta línea (renueva el token cada 6 horas con margen de seguridad):
0 */6 * * * aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 123456789012.dkr.ecr.us-east-1.amazonaws.com >> /var/log/ecr-login.log 2>&1
```

> **Por qué cada 6 horas y no 12:** si el cron falla una vez, el token no habría
> expirado todavía. Cada 12 horas no deja margen de error.

### 3.12 Preparar docker-compose.prod.yml

Crear en la raíz del proyecto local:

```yaml
services:
  web:
    image: ${ECR_REGISTRY}/todos:${TAG:-staging-latest}
    command: >
      sh -c "python manage.py migrate --no-input &&
             python manage.py collectstatic --no-input &&
             gunicorn core.wsgi:application --bind 0.0.0.0:8000 --workers 2"
    env_file: .env
    ports:
      - "80:8000"
    restart: unless-stopped
```

> **Diferencia con el tutorial de DO:** la variable se llama `ECR_REGISTRY` y contiene
> el URI completo del registry (`123456789012.dkr.ecr.us-east-1.amazonaws.com`).
> El nombre del repositorio (`todos`) va en el archivo porque en ECR el repositorio
> es una entidad propia del registry.

Copiar a cada instancia:
```bash
scp -i ~/.ssh/todos-deploy-key.pem docker-compose.prod.yml ubuntu@<IP_EC2>:/opt/todos/
```

---

## Fase 4 — CD automatizado con AWS

**Objetivo:** merge a `develop` → deploy a staging. Merge a `main` → deploy a producción.

### 4.1 Secrets en GitHub

En **Settings → Secrets and variables → Actions**:

| Secret | Valor | Ejemplo |
|--------|-------|---------|
| `AWS_ACCESS_KEY_ID` | Access Key ID del IAM user `github-actions-deploy` | `AKIAIOSFODNN7EXAMPLE` |
| `AWS_SECRET_ACCESS_KEY` | Secret Access Key del mismo usuario | `wJalrXUtnFEMI/...` |
| `AWS_REGION` | Región donde creaste ECR y RDS | `us-east-1` |
| `ECR_REGISTRY` | URI del registry (sin el nombre del repo) | `123456789012.dkr.ecr.us-east-1.amazonaws.com` |
| `ECR_REPOSITORY` | Nombre del repositorio en ECR | `todos` |
| `STAGING_HOST` | IP pública de la EC2 de staging | `54.123.45.67` |
| `PRODUCTION_HOST` | IP pública de la EC2 de producción | `54.234.56.78` |
| `SSH_PRIVATE_KEY` | Contenido completo del archivo `.pem` | (incluir líneas BEGIN/END) |
| `STAGING_DJANGO_SECRET_KEY` | Secret key para staging | (generada con Django) |
| `PRODUCTION_DJANGO_SECRET_KEY` | Secret key para producción | (generada con Django) |

> **Generar SECRET_KEY seguras (una diferente para staging y otra para producción):**
> ```bash
> python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
> ```

> **SSH_PRIVATE_KEY con AWS:** copiar el contenido completo del `.pem`, incluyendo
> las líneas `-----BEGIN RSA PRIVATE KEY-----` y `-----END RSA PRIVATE KEY-----`.

### 4.2 Workflow de CD — Staging

`.github/workflows/cd-staging.yml`:
```yaml
# ============================================================
# Workflow de CD — Deploy automático a Staging (AWS)
# ============================================================
# Se dispara en cada push a develop (merge de PR incluido).
# Construye la imagen, la sube a ECR y despliega en la EC2
# de staging vía SSH.
# ============================================================

name: CD — Staging

on:
  push:
    branches: [develop]

jobs:
  build-and-deploy:
    name: Build, push y deploy a staging
    runs-on: ubuntu-latest

    steps:
      - name: Checkout del código
        uses: actions/checkout@v4

      # Configura las credenciales de AWS en el runner.
      # Los pasos siguientes (ECR login, aws CLI) las usarán automáticamente.
      - name: Configurar credenciales de AWS
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ${{ secrets.AWS_REGION }}

      # Autentica Docker en ECR.
      # ECR usa tokens temporales (no user/password como DOCR).
      # Esta action ejecuta "aws ecr get-login-password | docker login" automáticamente.
      - name: Login a Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2

      # Construir y subir imagen con dos tags:
      # - staging-latest: siempre apunta a la última versión de staging (mutable)
      # - staging-<sha>: tag inmutable para rollback a commit exacto
      # linux/amd64 evita manifests multi-plataforma en el registry
      - name: Build y push de imagen Docker a ECR
        uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          platforms: linux/amd64
          tags: |
            ${{ secrets.ECR_REGISTRY }}/${{ secrets.ECR_REPOSITORY }}:staging-latest
            ${{ secrets.ECR_REGISTRY }}/${{ secrets.ECR_REPOSITORY }}:staging-${{ github.sha }}

      # Copiar docker-compose.prod.yml al servidor para asegurar
      # que siempre tiene la versión más reciente del código
      - name: Copiar docker-compose.prod.yml al servidor
        uses: appleboy/scp-action@v0.1.7
        with:
          host: ${{ secrets.STAGING_HOST }}
          username: ubuntu
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          source: docker-compose.prod.yml
          target: /opt/todos/

      # SSH a la EC2 de staging para bajar la nueva imagen y reiniciar.
      # Nota: el usuario es "ubuntu", no "root" como en DigitalOcean.
      # El IAM Instance Profile de la EC2 provee las credenciales para ECR
      # automáticamente — no se necesitan credenciales guardadas en el servidor.
      - name: Deploy en staging
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.STAGING_HOST }}
          username: ubuntu
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          script: |
            # Renovar token de ECR (el Instance Profile provee las credenciales)
            aws ecr get-login-password --region ${{ secrets.AWS_REGION }} | \
              docker login --username AWS --password-stdin ${{ secrets.ECR_REGISTRY }}

            # Bajar la nueva imagen
            docker pull ${{ secrets.ECR_REGISTRY }}/${{ secrets.ECR_REPOSITORY }}:staging-latest

            # Reiniciar el contenedor con la nueva imagen
            cd /opt/todos
            ECR_REGISTRY=${{ secrets.ECR_REGISTRY }} \
            TAG=staging-latest \
            docker compose -f docker-compose.prod.yml up -d

            # Limpiar imágenes viejas para liberar espacio en disco
            docker image prune -f
```

### 4.3 Workflow de CD — Producción

`.github/workflows/cd-production.yml`:
```yaml
# ============================================================
# Workflow de CD — Deploy automático a Producción (AWS)
# ============================================================
# Se dispara en cada push a main (siempre vía PR desde develop).
# Mismo flujo que staging pero apunta a la EC2 de producción.
# ============================================================

name: CD — Producción

on:
  push:
    branches: [main]

jobs:
  build-and-deploy:
    name: Build, push y deploy a producción
    runs-on: ubuntu-latest

    steps:
      - name: Checkout del código
        uses: actions/checkout@v4

      - name: Configurar credenciales de AWS
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ${{ secrets.AWS_REGION }}

      - name: Login a Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2

      # Tag "latest" para producción + tag inmutable con SHA para rollback
      - name: Build y push de imagen Docker a ECR
        uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          platforms: linux/amd64
          tags: |
            ${{ secrets.ECR_REGISTRY }}/${{ secrets.ECR_REPOSITORY }}:latest
            ${{ secrets.ECR_REGISTRY }}/${{ secrets.ECR_REPOSITORY }}:${{ github.sha }}

      - name: Copiar docker-compose.prod.yml al servidor
        uses: appleboy/scp-action@v0.1.7
        with:
          host: ${{ secrets.PRODUCTION_HOST }}
          username: ubuntu
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          source: docker-compose.prod.yml
          target: /opt/todos/

      - name: Deploy en producción
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.PRODUCTION_HOST }}
          username: ubuntu
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          script: |
            aws ecr get-login-password --region ${{ secrets.AWS_REGION }} | \
              docker login --username AWS --password-stdin ${{ secrets.ECR_REGISTRY }}

            docker pull ${{ secrets.ECR_REGISTRY }}/${{ secrets.ECR_REPOSITORY }}:latest

            cd /opt/todos
            ECR_REGISTRY=${{ secrets.ECR_REGISTRY }} \
            TAG=latest \
            docker compose -f docker-compose.prod.yml up -d

            docker image prune -f
```

### Errores comunes en Fase 3 y 4 (AWS)

| Error | Causa | Solución |
|-------|-------|----------|
| `no basic auth credentials` al hacer push a ECR desde el runner | Las credenciales de AWS no están configuradas | Verificar que `AWS_ACCESS_KEY_ID` y `AWS_SECRET_ACCESS_KEY` son correctos en GitHub Secrets |
| `denied: User: arn:aws:iam::...` al hacer push a ECR | El usuario IAM no tiene permisos de push | Verificar que la política inline del usuario incluye `ecr:PutImage`, `ecr:InitiateLayerUpload`, etc. |
| `Unable to locate credentials` en la EC2 | IAM Instance Profile no está adjunto o AWS CLI no está instalado | En EC2 Console → Actions → Security → Modify IAM role → adjuntar `ec2-ecr-pull-role` |
| `Permission denied (publickey)` en el paso SSH del workflow | Contenido incorrecto en `SSH_PRIVATE_KEY` o usuario equivocado | Verificar que el usuario es `ubuntu` (no `root`) y que el secret contiene el `.pem` completo |
| `could not connect to server` al conectar a RDS desde la EC2 | Security Group de RDS no permite conexiones de la EC2 | En `rds-todos-sg`, agregar inbound rule: TCP/5432 desde el security group `ec2-todos-sg` |
| `ssh: connect to host ... Connection timed out` en el workflow | Security Group de EC2 no permite SSH desde los runners de GitHub | Agregar inbound rule: TCP/22 desde `0.0.0.0/0` (o desde los rangos IP publicados por GitHub) |
| `exec format error` al iniciar el contenedor en la EC2 | Imagen construida para ARM (Mac M1/M2) y EC2 es x86 | Agregar `platforms: linux/amd64` al paso de build (ya incluido en los workflows de este tutorial) |
| El token de ECR expiró entre deploys | El token dura 12h — si el cronjob falló y pasaron 12h | Ejecutar manualmente `aws ecr get-login-password ... | docker login ...` en la EC2 |

### 4.4 Flujo completo end-to-end

```
1. Developer crea rama: git checkout -b feature/nueva-funcionalidad
2. Desarrolla, commitea y hace push
3. Abre PR: feature/nueva-funcionalidad → develop
4. GitHub Actions corre CI automáticamente
5. Con CI verde + aprobación: merge a develop
6. CD de staging se dispara automáticamente:
   a. GitHub Actions autentica en ECR con credenciales IAM del usuario
   b. Construye la imagen Docker (linux/amd64)
   c. Sube la imagen con tags staging-latest y staging-<sha>
   d. SSH a la EC2 de staging (usuario: ubuntu)
   e. EC2 renueva token de ECR usando su IAM Instance Profile
   f. docker pull de la nueva imagen
   g. docker compose up -d → migrate + collectstatic + gunicorn
7. App actualizada en staging en ~2 minutos
8. QA verifica en staging: curl http://<IP_STAGING>/api/todos/
9. Abre PR: develop → main
10. CI corre en el PR
11. Con CI verde + aprobación: merge a main
12. CD de producción se dispara con el mismo flujo
13. App en producción actualizada
```

---

## Fase 5 — Buenas prácticas finales

### Health check endpoint

Agregar en `apps/todos/views.py`:
```python
from rest_framework.decorators import api_view
from rest_framework.response import Response

@api_view(["GET"])
def health_check(request):
    return Response({"status": "ok"})
```

En `core/urls.py`:
```python
from apps.todos.views import health_check

urlpatterns = [
    path("health/", health_check),
    ...
]
```

### Rollback básico

```bash
# Opción 1 (recomendada): revertir el commit en main
git revert HEAD
git push origin main
# → CD de producción reconstruye imagen sin el cambio problemático

# Opción 2: rollback inmediato en el servidor
ssh -i ~/.ssh/todos-deploy-key.pem ubuntu@<IP_PRODUCCION>
cd /opt/todos
ECR_REGISTRY=123456789012.dkr.ecr.us-east-1.amazonaws.com \
TAG=<sha-del-commit-bueno> \
docker compose -f docker-compose.prod.yml up -d
```

### Desactivar los servicios al terminar

Para dejar de pagar cuando termines el ejercicio:

| Servicio | Acción | Costo que elimina |
|---|---|---|
| EC2 (staging + producción) | **Terminate instances** | ~$8.35/mes × 2 |
| RDS | **Delete** (desactivar snapshot final si es tutorial) | ~$13/mes |
| ECR | **Delete repository** | ~$0.03/mes |
| IAM User/Role | Opcional — no generan costo | $0 |

> **EC2 vs DO:** a diferencia de DigitalOcean donde "apagar" sigue cobrando,
> en AWS "Stop" (parar) reduce el costo (solo se cobra el almacenamiento EBS, ~$0.10/GB/mes).
> "Terminate" (terminar) elimina la instancia completamente y deja de cobrar.

### Checklist de producción (AWS)

- [ ] `DEBUG=False` en producción
- [ ] `SECRET_KEY` en GitHub Secrets, no en el código
- [ ] `ALLOWED_HOSTS` restringido al dominio/IP real
- [ ] HTTPS activo (Let's Encrypt con Certbot, o AWS Certificate Manager)
- [ ] Backups automáticos de RDS activados (7 días por defecto)
- [ ] `.env` en `.gitignore` — nunca commitear credenciales
- [ ] Ramas `main` y `develop` protegidas (requieren PR + CI verde)
- [ ] Migraciones corriendo dentro del contenedor antes de levantar Gunicorn
- [ ] `restart: unless-stopped` en docker-compose.prod.yml
- [ ] WhiteNoise configurado para archivos estáticos
- [ ] IAM Instance Profile adjunto a las EC2 (sin credenciales en el servidor)
- [ ] Security Groups: EC2 puede conectar a RDS en puerto 5432
- [ ] Cronjob de renovación de token ECR configurado en cada EC2 (cada 6 horas)
- [ ] Usuario SSH es `ubuntu`, verificado en los workflows
- [ ] `platforms: linux/amd64` en los workflows de build
- [ ] Política IAM del usuario `github-actions-deploy` con mínimo privilegio

---

## Referencia rápida

### Comandos locales frecuentes

```bash
# Levantar el stack completo
docker compose up --build

# Generar migración después de cambiar un modelo
docker compose exec web python manage.py makemigrations todos

# Aplicar migraciones
docker compose exec web python manage.py migrate

# Correr los tests
docker compose exec web python manage.py test apps.todos --verbosity=2

# Ver logs en tiempo real
docker compose logs -f web
```

### Comandos en el servidor (EC2)

```bash
# Conectar al servidor
ssh -i ~/.ssh/todos-deploy-key.pem ubuntu@<IP_EC2>

# Renovar token de ECR manualmente
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  123456789012.dkr.ecr.us-east-1.amazonaws.com

# Ver estado del contenedor
cd /opt/todos
docker compose -f docker-compose.prod.yml ps

# Ver logs en tiempo real
docker compose -f docker-compose.prod.yml logs -f web

# Reiniciar el contenedor
docker compose -f docker-compose.prod.yml restart web

# Shell dentro del contenedor
docker compose -f docker-compose.prod.yml exec web python manage.py shell

# Rollback a versión anterior
ECR_REGISTRY=123456789012.dkr.ecr.us-east-1.amazonaws.com \
TAG=<sha-del-commit> \
docker compose -f docker-compose.prod.yml up -d

# Limpiar imágenes viejas
docker image prune -f
```

### Comandos AWS CLI útiles

```bash
# Verificar identidad configurada localmente
aws sts get-caller-identity

# Listar repositorios ECR
aws ecr describe-repositories --region us-east-1

# Listar imágenes en el repositorio
aws ecr list-images --repository-name todos --region us-east-1

# Ver instancias EC2 activas
aws ec2 describe-instances --region us-east-1 \
  --query 'Reservations[].Instances[].[InstanceId,PublicIpAddress,State.Name]' \
  --output table

# Ver endpoint de RDS
aws rds describe-db-instances --region us-east-1 \
  --query 'DBInstances[].[DBInstanceIdentifier,Endpoint.Address]' \
  --output table
```

### Estructura de archivos final

```
my_first_ci_cd_pipeline/
├── .github/
│   └── workflows/
│       ├── ci.yml              # Tests en cada push/PR (idéntico al tutorial de DO)
│       ├── cd-staging.yml      # Deploy a staging (usa ECR + usuario ubuntu)
│       └── cd-production.yml   # Deploy a producción (usa ECR + usuario ubuntu)
├── apps/
│   └── todos/
│       ├── migrations/
│       ├── tests/
│       ├── __init__.py
│       ├── apps.py
│       ├── models.py
│       ├── serializers.py
│       ├── urls.py
│       └── views.py
├── core/
│   ├── settings/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── local.py
│   │   └── production.py
│   ├── __init__.py
│   ├── asgi.py
│   ├── urls.py
│   └── wsgi.py
├── plans/
│   ├── aprendizaje-cicd.md        # Plan de aprendizaje (DigitalOcean)
│   ├── tutorial-cicd.md           # Tutorial completo DigitalOcean
│   └── tutorial-cicd-aws.md       # Este archivo
├── requirements/
│   ├── base.txt
│   ├── local.txt
│   └── production.txt
├── .env                            # Local (NO va a git)
├── .env.example                    # Plantilla documentada (va a git)
├── .gitignore
├── Dockerfile
├── docker-compose.yml              # Desarrollo local
├── docker-compose.prod.yml         # Producción/staging (usa imagen de ECR)
└── manage.py
```
