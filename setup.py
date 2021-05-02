from setuptools import setup


setup(
    name="freecad.lumberjack",
    version="0.0.0dev",
    url="https://github.com/tomster/FreeCAD-lumberjack",
    description="Woodworking workbench for FreeCAD",
    packages=["freecad", "freecad.lumberjack"],
    include_package_data=True,
    # install_requires=["freecad.asm3"],
    namespace_packages=["freecad"],
    extras_require={"development": ["pytest", "pytest-mock"]},
)
