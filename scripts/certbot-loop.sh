#!/bin/sh
set -eu

if [ -z "${CERTBOT_EMAIL:-}" ]; then
  echo "CERTBOT_EMAIL is required"
  exit 1
fi

if [ -z "${CERTBOT_DOMAINS:-}" ]; then
  echo "CERTBOT_DOMAINS is required (comma-separated)"
  exit 1
fi

# Build repeated -d args from a comma-separated domain list.
domain_args=""
old_ifs=$IFS
IFS=','
for d in $CERTBOT_DOMAINS; do
  d=$(echo "$d" | xargs)
  if [ -n "$d" ]; then
    domain_args="$domain_args -d $d"
  fi
done
IFS=$old_ifs

if [ -z "$domain_args" ]; then
  echo "No valid domains found in CERTBOT_DOMAINS"
  exit 1
fi

cert_name_args=""
if [ -n "${CERT_NAME:-}" ]; then
  cert_name_args="--cert-name $CERT_NAME"
fi

# shellcheck disable=SC2086
certbot certonly --webroot -w /var/www/certbot \
  --email "$CERTBOT_EMAIL" \
  --agree-tos --no-eff-email \
  --non-interactive \
  --keep-until-expiring \
  $cert_name_args \
  $domain_args

while :; do
  certbot renew --webroot -w /var/www/certbot --quiet || true
  sleep 12h
done
