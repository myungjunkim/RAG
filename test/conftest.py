def pytest_addoption(parser):
    parser.addoption("--active-profile", action="store", default="local")
