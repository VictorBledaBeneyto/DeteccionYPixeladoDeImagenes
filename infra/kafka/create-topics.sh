#!/bin/bash
set -e

KAFKA="kafka:9092"

topics=(
  "images.raw.send"
  "images.faces_detected"
  "images.faces_detected.send"
  "images.age_estimated"
  "images.age_estimated.send"
  "images.processed"
)

for topic in "${topics[@]}"; do
  /opt/kafka/bin/kafka-topics.sh --bootstrap-server "$KAFKA" \
    --create --if-not-exists \
    --topic "$topic" \
    --partitions 1 \
    --replication-factor 1
  echo "Topic '$topic' ready."
done
