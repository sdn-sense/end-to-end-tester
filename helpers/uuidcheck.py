import pprint
from EndToEndTester.utilities import loadJson
from EndToEndTester.tester import SENSEWorker

worker = SENSEWorker([], 0, None)
output = worker._setFinalStats({}, {}, '7ae0d3f3-bcf4-4d2b-afbd-6deb2ad89fb9')
for key, value in output['validation'].items():
    print(key)
    print('---------')
    if isinstance(value, str):
        tmpdata = loadJson(value)
        for key1, val1 in tmpdata.items():
            print(key1)
            print('=====')
            print(val1)
#pprint.pprint(output)
