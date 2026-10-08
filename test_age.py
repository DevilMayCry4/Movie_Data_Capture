from cloudscraper import create_scraper
import re

s = create_scraper(browser={'custom': 'Mozilla/5.0 (iPad; CPU OS 11_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/11.0 Tablet/15E148 Safari/604.1'})

url = 'https://www.javbus.com/JUC-631'
r1 = s.get(url)
t1 = r1.text
print('STEP1 status:', r1.status_code, 'ageVerify:', 'ageVerify' in t1, 'len:', len(t1))
print('cookies after GET1:', dict(s.cookies))

# POST the confirm form to the same URL
data = {'Submit': '\u78ba\u8a8d', 'checkbox': 'on'}
r2 = s.post(url, data=data)
t2 = r2.text
print('STEP2 post status:', r2.status_code, 'ageVerify:', 'ageVerify' in t2, 'len:', len(t2))
print('cookies after POST:', dict(s.cookies))

# re-GET
r3 = s.get(url)
t3 = r3.text
print('STEP3 reget status:', r3.status_code, 'ageVerify:', 'ageVerify' in t3, 'len:', len(t3))
print('title:', re.findall(r'<title>(.*?)</title>', t3))
print('cookies after reGET:', dict(s.cookies))