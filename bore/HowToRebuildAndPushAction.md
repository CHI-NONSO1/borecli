Do not manully update code on github
git add .
git commit -m "Fix CLI authentication error handling"
git push origin main
git tag v1.4.1
git push origin v1.4.1


<!-- =====================PYPI===== -->
change version = "1.4.1" in project toml
python -m pip install -e . --upgrade
python -m pip install --upgrade build twine

Remove old build files
rmdir /S /Q dist
rmdir /S /Q build
rmdir /S /Q borecli.egg-info

python -m build

Validate them
python -m twine check dist/*

Upload to PyPI
python -m twine upload dist/*

<!-- ========================================NPM============================== -->
1.Log in to npm
npm login

2. Verify the login

npm whoami

4. Publish 1.4...
npm publish --access public