import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from tools.calocalc_tool import analizar_texto

casos = [
    'cene pollo a la brasa con papa',
    'almorce lomo saltado',
    'comi ceviche',
    'desayune avena con platano',
    'me comi un anticucho',
    'desayune dos huevos en omelette y cafe con leche',
    'almorce arroz chaufa con pollo',
    'comi arroz con leche',
]
for caso in casos:
    r = analizar_texto(caso)
    items = ', '.join(i['nombre'] + '(' + str(i['kcal']) + ')' for i in r['items'])
    print(caso + ' -> ' + str(r['totales']['kcal']) + ' kcal | ' + items)
