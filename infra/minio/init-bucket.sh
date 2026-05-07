#!/bin/sh
set -e

until mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" 2>/dev/null; do
  echo "Waiting for MinIO..."
  sleep 2
done

mc mb --ignore-existing local/images
mc anonymous set public local/images

echo "" | mc pipe local/images/originales/.keep
echo "" | mc pipe local/images/caras/.keep
echo "" | mc pipe local/images/marcos/.keep
echo "" | mc pipe local/images/definitivas/.keep

echo "MinIO bucket 'images' ready with originales/, caras/, marcos/ and definitivas/ prefixes."
