#!/bin/bash
# Route every example module. Same as: python3 -m rvsched route examples/*
cd "$(dirname "$0")" && python3 -m rvsched route examples/*.v examples/*.sv --store "${STORE:-.rvsched}"
