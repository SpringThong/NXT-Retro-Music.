#!/usr/bin/env python3
"""Publish owner-approved original releases; private development history stays private.

The runner creates a temporary transfer key. Only its public certificate and
encrypted file-transfer metadata pass through Git. The private key and clear
transfer metadata exist only in the runner temporary directory.
"""
from pathlib import Path
import base64
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

REPOSITORY = 'SpringThong/NXT-Retro-Music.'
VERSION = '1.9.7.7'
SOURCE_SHA = 'e5cb7b0488af2d6775c9be9a3a2e86c00a829159f5c3056e10a61f10b60ae992'
SOURCE_PREFIX = 'NXT_Retro_Music_v1.9.7.7_Source/'
EXPECTED = {
    'Stock':'66892730768bb583f604bee9cd5994170aa28fb8c57557f6531c1f0c4ebe2500',
    'NextUI':'6934d41b4849d1239c709eadf2fd2912288028c667d380a651ba0826d4332313',
    'NXRedux':'d660410b95ec76943d4fbbd595dffdd00140cfd245bd88dcfdc4c781c0b16bf1',
}

def gh_json(*args, payload=None):
    p = subprocess.run(['gh','api',*args], input=json.dumps(payload) if payload is not None else None,
        text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError('GitHub publication request failed')
    return json.loads(p.stdout)

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda:f.read(1024*1024), b''): h.update(data)
    return h.hexdigest()

def main():
    root=Path.cwd()
    setup=root/'.nxt-publish'
    actual=gh_json('repos/'+REPOSITORY)
    if actual.get('full_name') != REPOSITORY or actual.get('private'):
        raise ValueError('Expected the owner-approved public release repository')
    if os.environ.get('GITHUB_REPOSITORY') != REPOSITORY:
        raise ValueError('Unexpected workflow repository')
    with tempfile.TemporaryDirectory(prefix='nxt-public-',dir=os.environ.get('RUNNER_TEMP')) as temp:
        temp=Path(temp)
        private_key=temp/'transfer-private.pem'
        certificate=temp/'transfer-cert.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:3072','-nodes','-days','1',
            '-subj','/CN=NXT original release transfer/','-keyout',str(private_key),'-out',str(certificate)],
            check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        private_key.chmod(0o600)
        gh_json('repos/'+REPOSITORY+'/contents/.nxt-publish/transfer-cert.pem',
            '--method','PUT','--input','-',payload={
                'message':'Publish temporary public certificate for original release transfer',
                'content':base64.b64encode(certificate.read_bytes()).decode(),'branch':'main'})
        print('Temporary public transfer certificate ready.',flush=True)
        envelope=None
        for _ in range(90):
            p=subprocess.run(['gh','api','repos/'+REPOSITORY+'/contents/.nxt-publish/sealed-transfer.b64?ref=main'],
                text=True,capture_output=True)
            if p.returncode == 0:
                record=json.loads(p.stdout)
                envelope=base64.b64decode(base64.b64decode(record['content']).decode().strip(),validate=True)
                break
            time.sleep(10)
        if envelope is None: raise RuntimeError('Original release transfer was not supplied in time')
        encrypted=temp/'sealed.der'
        encrypted.write_bytes(envelope)
        clear=temp/'transfer.json'
        clear.touch(mode=0o600)
        subprocess.run(['openssl','cms','-decrypt','-binary','-inform','DER','-in',str(encrypted),
            '-recip',str(certificate),'-inkey',str(private_key),'-out',str(clear)],
            check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        config=json.loads(clear.read_text())
        clear.unlink()
        if config.get('repository') != REPOSITORY or not config['source'].get('download_url'):
            raise ValueError('Wrong file-transfer destination')
        source=temp/f'NXT_Retro_Music_v{VERSION}_Source.zip'
        p=subprocess.run([sys.executable,str(setup/'library_file_transfer.py'),'materialize',str(source)],
            input=json.dumps(config['source']),text=True,capture_output=True)
        if p.returncode: raise RuntimeError('Authorized source download failed')
        del config
        if digest(source) != SOURCE_SHA: raise ValueError('Original source checksum mismatch')
        print('Original complete source archive verified.',flush=True)
        source_bytes=source.read_bytes()
        assets=[]
        checksums=[]
        with zipfile.ZipFile(source) as snapshot:
            for rom,expected in EXPECTED.items():
                recipe=json.loads(gzip.decompress((setup/(rom+'.recipe.json.gz')).read_bytes()))
                name=f'NXT_Retro_Music_v{VERSION}_{rom}.zip'
                if recipe['target_name'] != name or recipe['target_sha256'] != expected:
                    raise ValueError('Unexpected installer recipe')
                target=temp/name
                with target.open('wb') as out:
                    for operation in recipe['operations']:
                        if 'copy' in operation:
                            offset,length=operation['copy']
                            if min(offset,length)<0 or offset+length>len(source_bytes):
                                raise ValueError('Invalid original byte range')
                            out.write(source_bytes[offset:offset+length])
                        elif 'literal' in operation:
                            out.write(base64.b64decode(operation['literal'],validate=True))
                        else: raise ValueError('Unexpected transfer operation')
                if target.stat().st_size != recipe['target_size'] or digest(target) != expected:
                    raise ValueError('Original installer checksum mismatch: '+rom)
                report=json.loads(snapshot.read(SOURCE_PREFIX+f'BUILD_REPORT_v{VERSION}_{rom}.json'))
                if report['installer_sha256'] != expected:
                    raise ValueError('Original build report mismatch: '+rom)
                with zipfile.ZipFile(target) as z:
                    if z.testzip() is not None: raise ValueError('Installer ZIP CRC failure: '+rom)
                assets.append(target)
                checksums.append(expected+'  '+name)
                print('Original '+rom+' installer verified.',flush=True)
        del source_bytes
        checksums.append(SOURCE_SHA+'  '+source.name)
        checksum=temp/'SHA256SUMS.txt'
        checksum.write_text('\n'.join(checksums)+'\n')
        if checksum.read_bytes() != (root/'SHA256SUMS.txt').read_bytes():
            raise ValueError('Published documentation checksum list mismatch')
        notes=temp/'release-notes.md'
        shutil.copyfile(root/'release-notes.md',notes)
        receipt={
            'version':VERSION,'original_binaries_rebuilt':False,
            'installer_sha256_verified':EXPECTED,'original_source_sha256':SOURCE_SHA,
            'source_provided_as_separate_release_asset':True,
            'development_repository_history_published':False,
            'ota_feeds_modified':False,
        }
        (root/'docs'/'RELEASE_VERIFICATION_v1.9.7.7.json').write_text(json.dumps(receipt,indent=2)+'\n')
        # Remove only this task's temporary publication files and workflow.
        # Application source stays in the separate release ZIP, never this Git history.
        shutil.rmtree(setup)
        (root/'.github/workflows/publish-nxt-v1977.yml').unlink()
        subprocess.run(['git','pull','--ff-only'],check=True,stdout=subprocess.DEVNULL)
        # The latest pull includes the temporary encrypted transfer; delete again.
        if setup.exists(): shutil.rmtree(setup)
        subprocess.run(['git','config','user.name','github-actions[bot]'],check=True)
        subprocess.run(['git','config','user.email','41898282+github-actions[bot]@users.noreply.github.com'],check=True)
        subprocess.run(['git','add','--all'],check=True)
        subprocess.run(['git','commit','-m','Finalize verified public release and remove temporary publisher'],check=True,stdout=subprocess.DEVNULL)
        subprocess.run(['git','push','origin','HEAD:main'],check=True,stdout=subprocess.DEVNULL)
        head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
        subprocess.run(['gh','release','create','v'+VERSION,'--repo',REPOSITORY,'--target',head,
            '--title','NXT Retro Music v'+VERSION,'--notes-file',str(notes),'--draft',
            *map(str,assets),str(source),str(checksum)],check=True)
        subprocess.run(['gh','release','edit','v'+VERSION,'--repo',REPOSITORY,'--draft=false'],check=True)
        print('Public release published: three original installers, complete matching source and checksums.',flush=True)

if __name__=='__main__': main()
