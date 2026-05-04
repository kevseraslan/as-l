import urllib.request, re
try:
    req = urllib.request.Request('https://www.pinterest.com/pin/5770305767786178/', headers={'User-Agent': 'Mozilla/5.0'})
    html = urllib.request.urlopen(req).read().decode('utf-8')
    m = re.search(r'"contentUrl":"(https://[^"]+\.mp4)"', html)
    print(m.group(1) if m else 'No video')
except Exception as e:
    print(e)
