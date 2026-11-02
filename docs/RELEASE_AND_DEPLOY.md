# Releases y despliegue

El workflow `.github/workflows/release-and-deploy.yml` se ejecuta al recibir un
push a `main` (incluido un merge) y también puede iniciarse manualmente.

Cada ejecución:

1. calcula el siguiente tag patch (`vX.Y.Z`, partiendo de `v0.1.0` si no existe
   ninguno);
2. construye y prueba el frontend;
3. crea el GitHub Release únicamente después de que el build termina bien;
4. publica el artefacto inmutable y lo despliega por SSH;
5. reinicia `minime-api` y `minime-scheduler` y exige un `/health` saludable.

El job de producción usa el environment `production`, por lo que sus reglas de
aprobación de GitHub se aplican antes del SSH.

## Secrets requeridos

Configurar en el environment `production`:

- `DEPLOY_HOST`: hostname o IP del servidor.
- `DEPLOY_USER`: usuario SSH de despliegue.
- `DEPLOY_PATH`: ruta de la aplicación, por ejemplo `/opt/minime/app`.
- `DEPLOY_SSH_PRIVATE_KEY`: clave privada dedicada al despliegue.
- `DEPLOY_KNOWN_HOSTS`: salida fijada de `ssh-keyscan` para el servidor.

El usuario debe poder ejecutar por `sudo` el desempaquetado, `systemctl` y los
servicios de la aplicación. El workflow no ejecuta migraciones de base de datos;
las migraciones requieren un paso operativo separado y autorizado.
