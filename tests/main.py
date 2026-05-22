import pytest
from hello import dothing

print("hello test")

def test_dothing():
    assert dothing() == 42