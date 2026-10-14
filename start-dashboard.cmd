@echo off
pushd "%~dp0"
py -3 drilling_sync.py --watch 300 --serve
popd
pause
