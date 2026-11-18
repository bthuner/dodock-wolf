#!/usr/bin/env bash
# Wazuh manager (the "ids" profile): read the bench's nginx log, as a manager does with a web
# server's logs it receives. Run by the image before Wazuh starts (/entrypoint-scripts).
set -euo pipefail
CONF=/var/ossec/etc/ossec.conf
grep -q wolf-nginx "$CONF" && exit 0
sed -i '0,/<\/ossec_config>/s##  <localfile>\n    <log_format>apache</log_format>\n    <location>/var/log/wolf-nginx/combined.log</location>\n  </localfile>\n</ossec_config>#' "$CONF"
echo "wolf demo: Wazuh reads /var/log/wolf-nginx/combined.log"
