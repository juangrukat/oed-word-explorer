"""Run the private dictionary server: python3 -m oed.server."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, urlsplit
from .service import Dictionary

ROOT=Path(__file__).resolve().parents[1]


def handler(dictionary):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, body, content_type='application/json; charset=utf-8'):
            if isinstance(body, (dict,list)):
                body=json.dumps(body,ensure_ascii=False).encode('utf-8')
            elif isinstance(body,str):
                body=body.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Cache-Control','no-store' if content_type.startswith('application/json') else 'no-cache')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url=urlsplit(self.path)
            params=parse_qs(url.query)
            def value(key,default=''):
                return params.get(key,[default])[0]
            try:
                if url.path in {'/','/app.js','/style.css'}:
                    name={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}[url.path]
                    kind={'/':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8'}[url.path]
                    self.respond(200,(ROOT/'web'/name).read_bytes(),kind)
                elif url.path=='/api/status':
                    self.respond(200,dictionary.status())
                elif url.path=='/api/search':
                    mode=value('mode','headword')
                    if mode not in {'headword','definitions','quotations','rhyme','near-rhyme','sounds-like'}:
                        raise ValueError('Unknown search mode')
                    self.respond(200,dictionary.search(value('q'),mode,value('obscure')=='1',value('literary')=='1',
                        pos=value('pos','any'),syllables=int(value('syllables')) if value('syllables') else None,
                        stress=value('stress'),pronunciation=value('pronunciation'),input_type=value('input','word')))
                elif url.path=='/api/entry':
                    self.respond(200,dictionary.get_entry(int(value('id'))))
                elif url.path=='/api/related':
                    self.respond(200,dictionary.related(int(value('id')),value('sense') or None,value('obscure')=='1',value('literary')=='1'))
                elif url.path=='/api/quotations':
                    offset=int(value('offset','0'))
                    if offset<0 or offset>100000:
                        raise ValueError('Invalid quotation offset')
                    self.respond(200,dictionary.quotations(int(value('id')),offset))
                elif url.path=='/api/raw':
                    self.respond(200,dictionary.raw(int(value('id'))),'text/plain; charset=us-ascii')
                else:
                    self.respond(404,{'error':'Not found'})
            except KeyError as error:
                self.respond(404,{'error':str(error.args[0])})
            except ValueError as error:
                self.respond(400,{'error':str(error)})
            except (BrokenPipeError,ConnectionResetError):
                pass
            except sqlite3.OperationalError:
                logging.exception('Database query failed')
                self.respond(503,{'error':'Query unavailable. Try a more specific search.'})
            except Exception:
                logging.exception('Request failed')
                self.respond(500,{'error':'Unable to read this entry. See the server log.'})

        def log_message(self, fmt, *args):
            logging.info('%s - %s',self.address_string(),fmt % args)
    return Handler


def main():
    parser=argparse.ArgumentParser(description='Private, read-only OED server')
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--database',type=Path,default=ROOT/'data/oed.sqlite')
    parser.add_argument('--corpus',type=Path,default=ROOT/'data/corpus.sgml')
    args=parser.parse_args()
    if not args.database.is_file() or not args.corpus.is_file():
        parser.error('Dictionary data is missing. Follow the import steps in README.md.')
    dictionary=Dictionary(args.database,args.corpus)
    expected=dictionary.status()['corpus_sha256']
    digest=hashlib.sha256()
    with args.corpus.open('rb') as f:
        while chunk:=f.read(1024*1024):
            digest.update(chunk)
    if digest.hexdigest()!=expected:
        parser.error('Corpus checksum does not match the imported database.')
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
    server=ThreadingHTTPServer((args.host,args.port),handler(dictionary))
    print(f'OED research server: http://{args.host}:{args.port}',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__=='__main__':
    main()
