"""ИНН российских организаций: проверка контрольной суммы и генерация.

Используется в двух местах:
- генератор тестовых данных (скрипт seed) — чтобы на портале были
  правдоподобные реквизиты;
- будущая валидация извлечённых из документов полей (узел validate графа):
  ИНН, не прошедший проверку суммы, — верный признак галлюцинации модели.
"""

import random

WEIGHTS_INN_10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)


def inn_is_valid(inn: str) -> bool:
    """Проверка 10-значного ИНН юридического лица по контрольной цифре."""
    inn = inn.strip()
    if not (inn.isdigit() and len(inn) == 10):
        return False
    digits = [int(d) for d in inn]
    control = sum(d * w for d, w in zip(digits[:9], WEIGHTS_INN_10)) % 11 % 10
    return control == digits[9]


def random_valid_inn(rng: random.Random) -> str:
    """Случайный ИНН с корректной контрольной суммой."""
    body = [rng.randint(0, 9) for _ in range(9)]
    control = sum(d * w for d, w in zip(body, WEIGHTS_INN_10)) % 11 % 10
    return "".join(map(str, body)) + str(control)
