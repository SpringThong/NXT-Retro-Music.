from pathlib import Path
import hashlib, json, os, subprocess, tempfile, zipfile
import gdown
REPO="SpringThong/NXT-Retro-Music."
FILES={
 "Stock":("1O6L9xvQSbidBJ72kUdnZQ-loFOGEagi3","66892730768bb583f604bee9cd5994170aa28fb8c57557f6531c1f0c4ebe2500"),
 "NextUI":("1mCnm1i2m59hAldfUHHDg7wGZlmm4yNk2","6934d41b4849d1239c709eadf2fd2912288028c667d380a651ba0826d4332313"),
 "NXRedux":("1S0y0WJuucuKzYwcLh4VZ1jkALggf12yM","d660410b95ec76943d4fbbd595dffdd00140cfd245bd88dcfdc4c781c0b16bf1"),
}
def digest(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
 return h.hexdigest()
assert os.environ["GITHUB_REPOSITORY"]==REPO
with tempfile.TemporaryDirectory(prefix="nxt-installers-",dir=os.environ.get("RUNNER_TEMP")) as t:
 t=Path(t); assets=[]; sums=[]; report={}
 for rom,(file_id,expected) in FILES.items():
  name="NXT_Retro_Music_v1.9.7.7_"+rom+".zip"; p=t/name
  result=gdown.download(id=file_id,output=str(p),quiet=True)
  if not result:raise RuntimeError("Public installer download failed: "+rom)
  if digest(p)!=expected:raise ValueError("Installer checksum mismatch: "+rom)
  with zipfile.ZipFile(p) as z:
   if z.testzip() is not None:raise ValueError("Installer ZIP CRC failed: "+rom)
  assets.append(p);sums.append(expected+"  "+name)
  report[name]={"sha256":expected,"bytes":p.stat().st_size,"public_drive_id":file_id}
  print("Original "+rom+" installer SHA-256 and ZIP CRC verified.",flush=True)
 sums_file=t/"SHA256SUMS-installers.txt";sums_file.write_text("\n".join(sums)+"\n")
 notes=t/"notes.md"
 notes.write_text("# NXT Retro Music v1.9.7.7\n\nOriginal Stock, NextUI and NX Redux installers, copied from the publisher's public OTA downloads and verified against their original SHA-256 checksums. No application rebuild or OTA feed changes.\n\nInstallation: close NXT, back up your app data, and extract the ZIP matching your ROM into the SD-card root.\n\nDraft: pending complete corresponding source availability before public publication. The private development repository and commit history remain private.\n")
 # Remove only this task's one-time uploader after downloads have been verified.
 subprocess.run(["git","config","user.name","github-actions[bot]"],check=True)
 subprocess.run(["git","config","user.email","41898282+github-actions[bot]@users.noreply.github.com"],check=True)
 Path(".github/workflows/upload-public-installers.yml").unlink()
 Path(".github/workflows/check-public-ota.yml").unlink()
 Path(".release-publish/upload.py").unlink()
 subprocess.run(["git","add","--all"],check=True)
 subprocess.run(["git","commit","-m","Remove completed one-time public installer uploader"],check=True,stdout=subprocess.DEVNULL)
 subprocess.run(["git","push","origin","HEAD:main"],check=True,stdout=subprocess.DEVNULL)
 head=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
 subprocess.run(["gh","release","create","v1.9.7.7","--repo",REPO,"--target",head,"--title","NXT Retro Music v1.9.7.7","--notes-file",str(notes),"--draft",*map(str,assets),str(sums_file)],check=True)
 print("All three original installers uploaded to the draft release.",flush=True)
 print(json.dumps(report),flush=True)
