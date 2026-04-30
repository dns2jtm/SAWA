#!/bin/bash
pip install awscli -q
aws configure set aws_access_key_id user_3CnIYaKyRxmjgtq3X7thNPUWGi5
aws configure set aws_secret_access_key rps_IWI8L2LZ5VQOHR5EM9G8TD0MFYFVNPBJBMS2H8C3776jqy
aws configure set default.region EU-RO-1
aws s3 cp s3://36bjod49gz/ftmo-eurgbp-backup.tar.gz /workspace/ \
  --endpoint-url https://s3api-eu-ro-1.runpod.io
cd /workspace && tar -xzf ftmo-eurgbp-backup.tar.gz
bash /workspace/ftmo-eurgbp/setup.sh
echo "✅ Fully restored"
echo "apt-get install -y libta-lib-dev && pip install TA-Lib ta 'pandas-ta==0.4.71b0' --ignore-requires-python" >> /workspace/ftmo-eurgbp/setup.sh
