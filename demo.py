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


class log:
  @staticmethod
  def info(msg):
    print(f'[INFO][{time.ctime()}] {msg}')

  @staticmethod
  def error(msg):
    print(f'[ERROR][{time.ctime()}] {msg}')

class DocumentHandler:
  def __init__(self, assets_map={}):
    self.fd = None
    self.assets_map = assets_map

  def handle_node(self, node, indent=0, prefix='', newline=True):
    """
    解析路径 block paragraph -> text
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

    elif node['kind'] == 'block':
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
          self.fd.write('![%s](%s)' % (node['data'].get('caption', node['key']), self.assets_map.get(node['data']['assetID'])))

      elif node['type'] == 'blockquote':
        self.fd.write('> ')
        for row in node['nodes']:
          self.handle_node(row)

      else:
        log.error(node)

      self.fd.write('\n')

    elif node['kind'] == 'document':
      for row in node['nodes']:
        self.handle_node(row, indent, prefix)
      return

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


def parse_index(data):
  soup = BeautifulSoup(data, 'html5lib')
  title = soup.title.text
  
  pattern = re.compile(r'window.GITBOOK_STATE = (.*);', re.MULTILINE | re.DOTALL)
  script = soup.find("script", text=pattern)
  match = pattern.search(script.text)
  data = json.loads(match.group(1))

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
    log.info(img_url)
    img_suffix = urllib.parse.unquote(img_url).split('?')[-2].split('/')[-1].split('.')[-1]
    img_filename = 'docs/assets/%s.%s' % (key, img_suffix)
    # print(urllib.parse.unquote(img_url).split('/?')[-2])
    download_assets(img_filename, img_url)
    assets_map[key] = 'assets/%s.%s' % (key, img_suffix)

  # handle page
  pages = new_data['content']['versions']['master']['pages']
  index = -1
  for k, v in pages.items():
    if index < 0:
      index += 1
      continue
    
    log.info(v['title'])
    log.info(v['description'])
    if v.get('documentURL'):
      json_url = cdn_prefix + re.search('documents.*$', v['documentURL']).group()
      filename = 'docs/%02d.json' % index

      json_data = get_json_data(filename, json_url)

      handler = DocumentHandler(assets_map=assets_map)
      handler.parse_gitlab_doc(json_data, filename='docs/%02d.md' % index, meta={
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

  r = requests.get(url, stream=True, headers={'User-Agent': 'Mozilla/5.0 (Windows; U; MSIE 9.0; Windows NT 9.0; en-US)'})
  with open(filename, 'wb') as f:
    r.raw.decode_content = True
    shutil.copyfileobj(r.raw, f)
  time.sleep(1)
  
if __name__ == '__main__':
  with open("docs/index.html") as f:
    parse_index(f.read())
    

  # exit()

  # with open("docs/document.json") as f:
  #   data = json.loads(f.read())

  # parse_gitlab_doc(data)
  