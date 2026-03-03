# task 4 - database 

## prereqs

assuming you have the following installed on your machine:
- [docker compose](https://docs.docker.com/compose/install/) 
- [uv](https://github.com/astral-sh/uv) 
- python 3.8+

## setup

### 1. start postgres container 
```bash
docker-compose up -d
```

### 2. create venv 
```bash
uv venv
source .venv/bin/activate  
```

### 3. install deps 
```bash
uv pip install -r requirements.txt
```

### 4. initialize database 
```bash
python init_db.py
```

## run it
```bash
flask run
```

runs at `http://127.0.0.1:5001`

## stopping the database
```bash
docker-compose down
```