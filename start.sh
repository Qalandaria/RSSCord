#!/bin/bash
docker build -t rsscord .
docker run --rm -v "$(pwd)":/app rsscord