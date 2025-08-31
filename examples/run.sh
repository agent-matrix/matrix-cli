rm -rf /home/ruslanmv/.matrix/runners/watsonx-chat/
# v2 inline manifest (runner embedded, simplest)
MODE=inline-v2 examples/watsonx-wow.sh

rm -rf /home/ruslanmv/.matrix/runners/watsonx-chat/
# v1 inline manifest (no runner in manifest → supply runner/repo)
MODE=inline-v1 examples/watsonx-wow.sh

rm -rf /home/ruslanmv/.matrix/runners/watsonx-chat/
# Hub-assisted (let Hub plan; if runner missing we fetch & bootstrap)
MODE=hub-assisted examples/watsonx-wow.sh

rm -rf /home/ruslanmv/.matrix/runners/watsonx-chat/
# Hub-assisted but force runner/repo flags up-front
MODE=hub-direct examples/watsonx-wow.sh