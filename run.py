from pathlib import Path
import os
import uvicorn
os.environ.setdefault('TRADEOPS_DSN',Path('.env.local').read_text(encoding='utf-8').strip())
if __name__=='__main__': uvicorn.run('tradeops.app:create_app',factory=True,host='127.0.0.1',port=8780)
