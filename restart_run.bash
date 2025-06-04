#!/bin/sh

rm -rf seeder_sources/**
rm -rf config_*
rm -rf torrents/*

git fetch --all
git pull


clear && python -m bittorrent_deployer.generate_sources --source-dir seeder_sources --torrents-dir torrents --config-dir . --template config.yaml --count 1 --size 4194304

git add --all .
git commit -m "auto data push"
git push


CPATH="config_1.yaml" python -m distributed_test
