#!/usr/bin/env python


import requests
import json
from bs4 import BeautifulSoup
import re
import json
from pprint import pprint
import time
import os.path
from io import StringIO
import shutil
import urllib
from PIL import Image
import sys
import hashlib
import logging as log

LOG_FORMAT = "[%(levelname)s] [%(asctime)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
log.basicConfig(level=log.INFO, format=LOG_FORMAT, datefmt=DATE_FORMAT, handlers=[log.StreamHandler()])

class DocumentHandler:
  def __init__(self, assets_map={}):
    self.fd = None
    self.assets_map = assets_map

  def handle_node(self, node, indent=0, prefix='', newline=True):
    """
    block paragraph -> text
    block table -> block table-row > block table-cell > block paragraph
    """

    if node['kind'] == 'range':
      if node['marks']:
        if node['marks'][0]['type'] == 'code':
          self.fd.write(prefix +'`' + node['text'] + '`')
        elif node['marks'][0]['type'] == 'bold' and not '#' in prefix:
          if node['text'].strip():
            self.fd.write(prefix + '**' + node['text'].strip() + '**')
          else:
            self.fd.write(prefix + node['text'])
        else:
          self.fd.write(prefix + node['text'])
      else:
        self.fd.write(prefix + node['text'])
      return 

    elif node['kind'] == 'text':
      # text
      self.handle_node(node['ranges'][0], indent, prefix)

      for row in node['ranges'][1:]:
        self.handle_node(row, indent, '')
      return

    elif node['kind'] in ('block', 'inline'):
      if node['type'] == 'paragraph':
        for row in node['nodes']:
          self.handle_node(row, indent, prefix)

        if not newline:
          return
        else:
          self.fd.write('\n')
          
      elif node['type'] == 'list-item':
        for row in node['nodes']:
          self.handle_node(row, indent, prefix=prefix, newline=False)
            
      elif node['type'] == 'list-unordered':
        if prefix.startswith('-'):
          prefix = '  ' + prefix
        else:
          prefix = '- '

        for row in node['nodes']:
          self.handle_node(row, indent=1, prefix=prefix)

      elif node['type'] == 'list-ordered':
        for index, row in enumerate(node['nodes']):
          self.handle_node(row, indent=1, prefix=str(index + 1) + '. ')

      elif node['type'].startswith('heading'):
        for row in node['nodes']:
          self.handle_node(row, indent=1, prefix='#' * int(node['type'].split('-')[-1]) + '# ')

      elif node['type'] == 'table-row':
        for row in node['nodes']:
          self.handle_node(row, indent)
        self.fd.write('|\n')

        if indent == -1:
          self.fd.write('|---' * len(node['nodes']) + '|\n')
        return

      elif node['type'] == 'table-cell':
        for row in node['nodes']:
          self.handle_node(row, indent, prefix='|', newline=False)
        return

      elif node['type'] == 'table':
        self.fd.write('\n')
        self.handle_node(node['nodes'][0], indent=-1)
        for row in node['nodes'][1:]:
          self.handle_node(row)

      elif node['type'] == 'image':
        self.fd.write('\n')
        if node['data'].get('assetID'):
          _asset = self.assets_map.get(node['data']['assetID'])
          self.fd.write('![%s](%s)\n' % (node['data'].get('caption', node['key']), _asset['value']))

          # download of need
          if not os.path.exists(_asset['filename']):
            download_assets(_asset['filename'], _asset['url'])

      elif node['type'] == 'blockquote':
        self.fd.write('> ')
        for row in node['nodes']:
          self.handle_node(row)

      elif node['type'] == 'code':
        self.fd.write('\n```\n')
        for row in node['nodes']:
          self.handle_node(row)
        # backspace 1byte
        self.fd.seek(self.fd.tell() - 1)
        self.fd.write('```\n')

      elif node['type'] in ('code-tab'):
        for row in node['nodes']:
          self.handle_node(row, newline=False)

      elif node['type'] in ('code-line'):
        for row in node['nodes']:
          self.handle_node(row)

      elif node['type'] == 'link':
        self.fd.write('[')
        for row in node['nodes']:
          self.handle_node(row, newline=False)
        self.fd.write('](%s)' % node['data'].get('href', '#'))

      else:
        log.error(node)

      self.fd.write('\n')

    elif node['kind'] in 'document':
      for row in node['nodes']:
        self.handle_node(row, indent, prefix)
      return

    else:
      log.error(node)

  def parse_gitlab_doc(self, data, meta=None, filename=None):
    # self.fd.seek(0)
    # self.fd.truncate(0)
    # new buffer
    self.fd = StringIO()
    if meta:
      self.fd.write('# %s\n\n' % meta['title'])
      if 'description' in meta:
        self.fd.write(f'> %s\n\n' % meta['description'])
    
    self.handle_node(data['document'])

    if filename:
      with open(filename, 'w+') as f:
        self.fd.seek(0)
        shutil.copyfileobj(self.fd, f)


def parse_gitbook_state(raw_data):
  soup = BeautifulSoup(raw_data, 'html5lib')
  title = soup.title.text

  pattern = re.compile(r'window.GITBOOK_STATE = (.*);', re.MULTILINE | re.DOTALL)
  script = soup.find("script", text=pattern)
  match = pattern.search(script.text)
  data = json.loads(match.group(1))
  return data


def parse_index(data, bid, page_index=None):
  cdn_prefix = data['config']['cdn']['blobsurl']
  log.info(cdn_prefix)

  database = data['state']['database']
  new_data = {}
  uid, primaryRevision = '', ''
  for k in database:
    tmp = re.findall(r'spaces/([^/]*)/revisions/([^/]*)', k)
    if tmp:
      uid, primaryRevision = tmp[0]
      new_data = database[k]['data']
      break

  # handle assets
  assets = new_data['content']['assets']
  assets_map = {}

  for key, asset in assets.items():
    img_url = cdn_prefix + re.search('assets.*$', asset['downloadURL']).group()
    # log.info(img_url)
    img_suffix = urllib.parse.unquote(img_url).split('?')[-2].split('/')[-1].split('.')[-1]
    img_filename = f'docs/{bid}/assets/{key}.{img_suffix}'
    # print(urllib.parse.unquote(img_url).split('/?')[-2])

    assets_map[key] = {
      'value': f'assets/{key}.{img_suffix}',
      'filename': img_filename,
      'url': img_url
    }

  # handle page
  pages = next(iter(new_data['content']['versions'].values()))['pages']
  index = -1
  for k, v in pages.items():
    if index < 0:
      index += 1
      continue

    if page_index and index != page_index:
      log.info('skip page %d %s' % (index, v['title']))
      index += 1
      continue

    log.info('new page %s: %s' % (v['title'], v['description']))
    if v.get('documentURL'):
      json_url = cdn_prefix + re.search('documents.*$', v['documentURL']).group()
      _filename = 'docs/%s/%02d %s' % (bid, index, v['title'])
      # filename = 'docs/%s/%02d.json' % (bid, index)

      json_data = get_json_data(_filename + '.json', json_url)

      handler = DocumentHandler(assets_map=assets_map)
      handler.parse_gitlab_doc(json_data, filename=_filename + '.md', meta={
        'title': v['title'],
        'description': v['description'],
      })

    index += 1

  log.info('- ' * 50)
  # 'https://gblobscdn.gitbook.com/documents/-LJsY0r5H3NzU5_tu-ZP/-L_R4CU5-vn5U6NazGIl/master/-LKfOzYLB1ae48PgF5Zc/document.json'
 

def get_json_data(filename, url):
  if os.path.exists(filename):
    return json.loads(open(filename).read())

  r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows; U; MSIE 9.0; Windows NT 9.0; en-US)'})
  json_data = r.text
  with open(filename, 'w+') as f:
    f.write(json_data)
  return json.loads(json_data)

def download_assets(filename, url):
  if os.path.exists(filename):
    return

  log.info(f"start download asset: {url}")
  r = requests.get(url, stream=True, headers={'User-Agent': 'Mozilla/5.0 (Windows; U; MSIE 9.0; Windows NT 9.0; en-US)'})
  with open(filename, 'wb') as f:
    r.raw.decode_content = True
    shutil.copyfileobj(r.raw, f)
  time.sleep(1)

def usage():
  print("Usage: ./export.py [url]")
  exit()
  
if __name__ == '__main__':
  # gitbook url
  if len(sys.argv) < 2:
    usage()

  url = sys.argv[1]

  bid = hashlib.md5(url.encode('utf8')).hexdigest()

  cache_file = f'./docs/{bid}/index.html'
  if os.path.exists(cache_file):
    log.info(f"get {bid} from cache")
    with open(cache_file) as f:
      raw_data = f.read()

    try:
      data = parse_gitbook_state(raw_data)
    except:
      log.error(f"parse gitbook state error")
      os.remove(cache_file)
      exit()

  else:
    log.info(f"get {bid} from request")
    try:
      r = requests.get(url)
    except:
      log.error(f"request {url} error")
      exit()

    raw_data = r.text

    try:
      data = parse_gitbook_state(raw_data)
    except Exception as e:
      log.error(f"parse gitbook state error: {e.__str__()}")
  
    if not os.path.exists(f'./docs/{bid}/assets'):
      os.makedirs(f'./docs/{bid}/assets', exist_ok=True)

    with open(cache_file, "w+") as f:
      f.write(raw_data)

  log.info(f"start parse {url} {bid}")
  if len(sys.argv) == 3:
    # convenient reget
    parse_index(data, bid, int(sys.argv[2]))
  else:
    parse_index(data, bid)

