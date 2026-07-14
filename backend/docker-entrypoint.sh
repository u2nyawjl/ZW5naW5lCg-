#!/bin/sh
set -e

# Identidad de commits aislada de la del host: los commits de la bóveda son del agente.
git config --global user.name  "${GIT_AUTHOR_NAME:-U2NyaWJl Agent}"
git config --global user.email "${GIT_AUTHOR_EMAIL:-agent@u2scribe.local}"
git config --global --add safe.directory /app/vault
git config --global init.defaultBranch main

# El token se expande cuando git invoca el helper, no ahora: nunca se escribe en ~/.gitconfig.
if [ -n "${VAULT_GITHUB_TOKEN}" ]; then
  git config --global credential.helper \
    '!f() { echo "username=x-access-token"; echo "password=${VAULT_GITHUB_TOKEN}"; }; f'
fi

exec "$@"
