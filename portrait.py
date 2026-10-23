"""User-supplied portrait formulas. No date storage or interpretation."""
import re
import unicodedata
from datetime import datetime, date, timedelta

def reduce22(n):
    if n < 0:
        raise ValueError('Зведення від’ємного числа потребує правила різниці.')
    return (n - 1) % 22 + 1

def calculate_social(value):
    """Sum every digit of the validated birth date, then reduce by 22."""
    calculate(value)
    return reduce22(sum(int(digit) for digit in value if digit.isdigit()))

def calculate_matrix(value):
    """Worksheet: fixed constant 2 before 2000, +19 from 01.01.2000.

    Keep all five working numbers unreduced; count digits 1..9 in the
    original date and every working number, including the constant.
    """
    calculate(value)
    born = datetime.strptime(value, '%d.%m.%Y').date()
    digit_sum = lambda n: sum(int(c) for c in str(n))
    first = sum(int(c) for c in value if c.isdigit())
    second = digit_sum(first)
    constant = 2 if born.year < 2000 else 19
    fourth = first - constant if born.year < 2000 else first + constant
    numbers = [first,second,constant,fourth,digit_sum(fourth)]
    digits = value + ''.join(map(str,numbers))
    counts = {i:digits.count(str(i)) for i in range(1,10)}
    return {'numbers':numbers,'counts':counts,'operation':'−' if born.year < 2000 else '+'}

UKRAINIAN_ALPHABET = 'АБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯ'
NAME_VALUES = {letter:i%9+1 for i,letter in enumerate(UKRAINIAN_ALPHABET)}

def normalize_money_name(value):
    name = ' '.join(unicodedata.normalize('NFC',value).split())
    letters = [c for c in name.upper() if c in NAME_VALUES]
    if not 1 <= len(letters) <= 80 or len(name) > 100 or any(
            c not in NAME_VALUES and c not in " -'’ʼ" for c in name.upper()):
        raise ValueError('Введіть лише ім’я українською, як у документах, без прізвища та по батькові. '
                         'Наприклад: Надія. Для подвійного імені дозволено дефіс або пробіл.')
    return name

def calculate_money(value,name):
    """User formula: R(9*П2 + П3 + R(sum of Ukrainian name letters)))."""
    portrait,_ = calculate(value)
    name = normalize_money_name(name)
    total = sum(NAME_VALUES.get(c,0) for c in name.upper())
    name_arcanum = reduce22(total)
    result = reduce22(9*portrait['П2']+portrait['П3']+name_arcanum)
    return {'name':name,'name_sum':total,'name_arcanum':name_arcanum,'arcanum':result}

def calculate_karma(value):
    """User's karma worksheet: ПП1 corrected to П4; zero differences become 22."""
    portrait, _ = calculate(value)
    p1,p2,p3 = (portrait[f'П{i}'] for i in (1,2,3))
    positive = [portrait['П4'],reduce22(p1+p3)]
    positive.append(reduce22(positive[0]+positive[1]))
    positive.append(reduce22(p2+p3))
    positive.append(reduce22(sum(positive)))
    negative = [reduce22(abs(p1-p2)),reduce22(abs(p1-p3))]
    negative.append(reduce22(abs(negative[0]-negative[1])))
    negative.append(reduce22(abs(p2-p3)))
    negative.append(reduce22(sum(negative)))
    return {'positive':positive,'negative':negative}

def calculate(value):
    if not re.fullmatch(r'\d{2}\.\d{2}\.\d{4}', value):
        raise ValueError('Введіть дату у форматі ДД.ММ.РРРР, наприклад 16.09.1998.')
    try:
        born = datetime.strptime(value, '%d.%m.%Y').date()
    except ValueError:
        raise ValueError('Такої календарної дати немає.') from None
    if born > date.today():
        raise ValueError('Дата народження не може бути в майбутньому.')
    p, steps = {}, []
    def put(key, nums, difference=False):
        raw = abs(nums[0]-nums[1]) if difference else sum(nums)
        result = reduce22(raw)
        p[key] = result
        expr = ' − '.join(map(str, nums)) if difference else ' + '.join(map(str, nums))
        if difference:
            expr = f'|{expr}|'
        chain = [str(raw)]
        while raw > 22:
            raw -= 22
            chain.append(str(raw))
        if raw == 0:
            chain.append('22')
        steps.append(f'{key}: {expr} = ' + ' → '.join(chain))
    put('П1', [born.day]); put('П2', [born.month])
    put('П3', list(map(int, str(born.year))))
    rules = {4:[1,2],5:[2,3],6:[4,5],7:[1,5],8:[2,6],9:[1,2],10:[2,3],11:[9,10],12:[7,8],13:[1,4,6],14:[3,5,6]}
    for k, sources in rules.items():
        put(f'П{k}', [p[f'П{i}'] for i in sources], k in (9,10,11))
    # Sum is NOT reduced before subtraction. Absolute difference follows the
    # supplied image's general karmic subtraction rule (larger minus smaller).
    s = p['П9'] + p['П10'] + p['П11']
    for k, sub in [('П15а','П7'),('П15б','П12')]:
        put(k, [s,p[sub]], True)
    for k, sources in {16:[1,3,4,5],17:[11,6],18:[11,8],19:[4,6],20:[5,6],21:[1,2,3,4,5,6],30:[12,12]}.items():
        put(f'П{k}', [p[f'П{i}'] for i in sources])
    for k,sources in {'A':['П1','П4'],'B':['П2','П4'],'C':['П2','П5'],'D':['П3','П5'],'E':['П4','П6'],'F':['П5','П6'],'G1':['C','D'],'G2':['B','F'],'H':['A','E'],'Кп':['П10','П6'],'J':['П2','П8']}.items():
        put(k,[p[i] for i in sources])
    return p, steps



def calculate_forecast(value,section,today):
    """Inclusive windows around a supplied local date; R subtracts 22 repeatedly."""
    portrait,_ = calculate(value)
    birth_sum = sum(int(c) for c in value if c.isdigit())
    digit_sum = lambda n: sum(int(c) for c in str(n) if c.isdigit())
    if section == 'year':
        return [(str(year),reduce22(portrait['П1']+portrait['П2']+reduce22(digit_sum(year))),
                 reduce22(birth_sum+reduce22(digit_sum(year))))
                for year in range(today.year-3,today.year+7)]
    if section == 'month':
        result=[]
        for offset in range(-6,18):
            year,month0=divmod(today.year*12+today.month-1+offset,12)
            month=month0+1
            result.append((f'{month:02d}.{year:04d}',
                           reduce22(portrait['П1']+month+reduce22(digit_sum(year)))))
        return result
    if section == 'day':
        days=[today+timedelta(days=offset) for offset in range(-5,26)]
        return [(day.strftime('%d.%m.%Y'),reduce22(birth_sum+digit_sum(day.strftime('%d%m%Y'))))
                for day in days]
    raise ValueError('Невідомий розділ прогнозу.')
