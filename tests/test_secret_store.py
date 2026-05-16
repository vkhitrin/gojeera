import sys
from types import ModuleType, SimpleNamespace

from gojeera.internal.store import secret


def test_set_password_uses_keyring_outside_macos_backend(monkeypatch):
    calls = []

    monkeypatch.setattr(secret, '_is_macos_keyring_backend', lambda: False)
    monkeypatch.setattr(
        secret.keyring,
        'set_password',
        lambda service_name, account_name, password: calls.append(
            (service_name, account_name, password)
        ),
    )

    secret._set_password('gojeera', 'basic_auth:user@example.com', 'api-token')

    assert calls == [('gojeera', 'basic_auth:user@example.com', 'api-token')]


def test_set_password_updates_existing_macos_keychain_item(monkeypatch):
    calls = []
    fake_api = _macos_api(calls, update_status=0)
    _install_fake_macos_api(monkeypatch, fake_api)

    secret._set_macos_password_preserving_access('gojeera', 'oauth:account-123', 'payload')

    _assert_macos_update_call(calls)


def test_set_password_adds_missing_macos_keychain_item(monkeypatch):
    calls = []
    fake_api = _macos_api(calls, update_status=-25300)
    _install_fake_macos_api(monkeypatch, fake_api)

    secret._set_macos_password_preserving_access('gojeera', 'oauth:account-123', 'payload')

    _assert_macos_update_call(calls)
    assert calls[1:] == [('add', None, 'gojeera', 'oauth:account-123', 'payload')]


def _install_fake_macos_api(monkeypatch, fake_api) -> None:
    macos_module = ModuleType('keyring.backends.macOS')
    setattr(macos_module, 'api', fake_api)
    monkeypatch.setitem(sys.modules, 'keyring.backends.macOS', macos_module)
    monkeypatch.setitem(sys.modules, 'keyring.backends.macOS.api', fake_api)


def _macos_api(calls: list[tuple], update_status: int):
    class NotFound(Exception):
        pass

    class Error(Exception):
        @classmethod
        def raise_for_status(cls, status):
            if status == -25300:
                raise NotFound
            if status != 0:
                raise cls(status)

    def create_query(**kwargs):
        return kwargs

    def sec_item_update(query, attributes):
        calls.append(('update', query, attributes))
        return update_status

    def set_generic_password(name, service_name, account_name, password):
        calls.append(('add', name, service_name, account_name, password))

    def cf_data_create(_, secret_bytes, secret_length):
        assert secret_bytes == b'payload'
        assert secret_length == len(b'payload')
        return 1234

    return SimpleNamespace(
        _found=SimpleNamespace(CFDataCreate=cf_data_create),
        _sec=SimpleNamespace(SecItemUpdate=sec_item_update),
        OS_status=int,
        Error=Error,
        NotFound=NotFound,
        create_query=create_query,
        k_=lambda key: key,
        set_generic_password=set_generic_password,
    )


def _assert_macos_update_call(calls: list[tuple]) -> None:
    assert calls[0][2]['kSecValueData'].value == 1234
    assert calls[0] == (
        'update',
        {
            'kSecClass': 'kSecClassGenericPassword',
            'kSecAttrService': 'gojeera',
            'kSecAttrAccount': 'oauth:account-123',
        },
        calls[0][2],
    )


def test_create_macos_secret_data_returns_void_pointer():
    calls = []
    fake_api = _macos_api(calls, update_status=0)

    assert secret._create_macos_secret_data(fake_api, 'payload').value == 1234
