from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from typing import Optional
import asyncpg
import json
from pydantic import BaseModel, Field
from google.cloud import storage
from google.oauth2 import service_account
import os
from starlette.responses import JSONResponse
import requests
import hashlib

# VALID_BEARER_TOKEN = os.environ.get("VALID_BEARER_TOKEN")

app = FastAPI()

# Database connection parameters
DATABASE_URL = os.environ.get("DATABASE_URL")

# Create a connection pool
async def create_pool():
    return await asyncpg.create_pool(
        DATABASE_URL
    )

pool = app.state.pool = None

class Page(BaseModel):
    title: str = Field("Multiverse", title="Title", description="The title of the page", max_length=100)
    slug: str = Field("multiverse", title="Slug", description="The slug of the page", max_length=100)
    content_html: str = Field("Welcome to the Multiverse!", title="Content HTML", description="The HTML content of the page")
    page_type: str = Field("landing", title="Page Type", description="The type of the page")
    metadata: dict = Field({}, title="Metadata", description="The metadata of the page")
    status: str = Field("published", title="Status", description="The status of the page")

class ImageFile(BaseModel):
    url: str = Field(..., title="URL", description="The URL of the image")


@app.on_event("startup")
async def startup_event():
    app.state.pool = await create_pool()
    ## test connection
    async with app.state.pool.acquire() as connection:
        pages = await connection.execute("SELECT count(*) FROM pages;")
        print(pages, " pages in the database")
        

@app.on_event("shutdown")
async def shutdown_event():
    await app.state.pool.close()

@app.post("/pages/")
async def create_page(request: Request, page: Page):
    
    # ## Check for valid bearer token 
    # if "Authorization" not in request.headers:
    #     raise HTTPException(status_code=401, detail="Unauthorized")
    # else:
    #     token = request.headers["Authorization"].split("Bearer ")[1]
    #     if token != VALID_BEARER_TOKEN:
    #         raise HTTPException(status_code=401, detail="Unauthorized")

    data = await request.json()
    print(data)
    title = data.get("title")
    slug = data.get("slug")
    content_html = data.get("content_html")
    page_type = data.get("page_type")
    metadata = json.dumps(data.get("metadata", {}))  # Convert dict to JSON string
    status = data.get("status")

    async with app.state.pool.acquire() as connection:
        try:
            page_id = await connection.fetchval(
                "INSERT INTO pages (title, slug, content_html, page_type, metadata, status) VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
                title, slug, content_html, page_type, metadata, status
            )
            return {"id": page_id, "title": title, "slug": slug, "url":"https://themultiverse.school/x/" + slug}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

## view page
@app.get("/pages/{page_id}")
async def get_page(request: Request, page_id: int):
    # ## Check for valid bearer token
    # if "Authorization" not in request.headers:
    #     raise HTTPException(status_code=401, detail="Unauthorized")
    # else:
    #     token = request.headers["Authorization"].split("Bearer ")[1]
    #     if token != VALID_BEARER_TOKEN:
    #         raise HTTPException(status_code=401, detail="Unauthorized")

    async with app.state.pool.acquire() as connection:
        try:
            page = await connection.fetchrow("SELECT * FROM pages WHERE id=$1", page_id)
            if page:
                return dict(page)
            else:
                raise HTTPException(status_code=404, detail="Page not found")
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        


## update page
@app.put("/pages/{page_id}")
async def update_page(request: Request, page_id: int, page: Page):
    # ## Check for valid bearer token
    # if "Authorization" not in request.headers:
    #     raise HTTPException(status_code=401, detail="Unauthorized")
    # else:
    #     token = request.headers["Authorization"].split("Bearer ")[1]
    #     if token != VALID_BEARER_TOKEN:
    #         raise HTTPException(status_code=401, detail="Unauthorized")

    data = await request.json()
    title = data.get("title")
    slug = data.get("slug")
    content_html = data.get("content_html")
    page_type = data.get("page_type")
    metadata = json.dumps(data.get("metadata", {}))
    status = data.get("status")
    
    async with app.state.pool.acquire() as connection:
        try:
            await connection.execute(
                "UPDATE pages SET title=$1, slug=$2, content_html=$3, page_type=$4, metadata=$5, status=$6 WHERE id=$7",
                title, slug, content_html, page_type, metadata, status, page_id
            )
            return {"id": page_id, "title": title, "slug": slug, "url":"https://themultiverse.school/x/" + slug}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        


# Google Cloud Storage configurations
GCS_BUCKET_NAME = 'multiverse-page-images'
SERVICE_ACCOUNT_FILE = './bucket_service_account.json'

# Initialize GCS client
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE
)
storage_client = storage.Client(credentials=credentials, project=credentials.project_id)

@app.post("/upload-image/")
async def upload_image_to_gcs(request: Request,file: UploadFile = File(...)):
    # ## Check for valid bearer token
    # if "Authorization" not in request.headers:
    #     raise HTTPException(status_code=401, detail="Unauthorized")
    # else:
    #     token = request.headers["Authorization"].split("Bearer ")[1]
    #     if token != VALID_BEARER_TOKEN:
    #         raise HTTPException(status_code=401, detail="Unauthorized")
    
    try:
        # Connect to the GCS bucket
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        
        # Create a new blob (object) in the bucket
        blob = bucket.blob(file.filename)
        
        # Upload the file
        await blob.upload_from_string(await file.read(), content_type=file.content_type)
        
        # Make the blob publicly accessible
        blob.make_public()
        
        # Return the public URL for the uploaded file
        return JSONResponse(status_code=200, content={"url": blob.public_url})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload-image-by-url/")
def upload_image_by_url(request: Request, ImageFile: ImageFile):
    # ## Check for valid bearer token
    # if "Authorization" not in request.headers:
    #     raise HTTPException(status_code=401, detail="Unauthorized")
    # else:
    #     token = request.headers["Authorization"].split("Bearer ")[1]
    #     if token != VALID_BEARER_TOKEN:
    #         raise HTTPException(status_code=401, detail="Unauthorized")
    
    try:
        # Connect to the GCS bucket
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        url = ImageFile.url
        ## hash the incoming url to create a unique filename
        filename = hashlib.md5(url.encode()).hexdigest()
        
        # Create a new blob (object) in the bucket
        blob = bucket.blob(filename)
        
        # Upload the file
        blob.upload_from_string(requests.get(url).content)
        
        # Make the blob publicly accessible
        blob.make_public()
        
        # Return the public URL for the uploaded file
        return JSONResponse(status_code=200, content={"url": blob.public_url})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
