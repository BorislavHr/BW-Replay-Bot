#!/bin/bash
echo "Downloading latest screp binary..."
curl -sL "https://github.com/icza/screp/releases/latest/download/screp_linux_amd64" -o screp
chmod +x screp
echo "screp ready"