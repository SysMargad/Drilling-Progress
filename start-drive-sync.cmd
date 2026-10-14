@echo off
pushd "%~dp0"
py -3 drilling_sync.py --source drive --watch 300 --publish
popd
pause
