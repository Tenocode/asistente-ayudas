# commit-push

Revisa el estado del repo, redacta un mensaje de commit que refleje lo trabajado en la sesión leyendo el README y el diff, commitea todos los cambios relevantes del proyecto y pushea a origin/main.

## Pasos

1. Ejecuta `git status` y `git diff` para ver qué ha cambiado.
2. Lee el README.md para entender el estado actual del proyecto y qué se ha hecho.
3. Redacta un mensaje de commit en español que resuma los cambios de la sesión (qué scripts se añadieron, qué fase se completó, qué datos se actualizaron).
4. Haz `git add` de todos los archivos relevantes del proyecto. No añadas: `venv/`, `data/convocatorias/*.pdf`, archivos `.env`, ni cualquier cosa en `.gitignore`.
5. Commitea con el mensaje redactado.
6. Pushea a origin main.
7. Confirma con el hash del commit y la URL del repo si está disponible.
