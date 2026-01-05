# main.py — COMPLETE UPDATED VERSION WITH ALL FEATURES
import os
import re
import urllib.parse
import json
import random
import shutil
import hashlib
import asyncio
from typing import List, Tuple, Dict, Optional
from datetime import datetime, timedelta

from fastapi import FastAPI, File, UploadFile, BackgroundTasks, Form, Request, Depends, HTTPException, status, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from starlette.requests import Request as StarletteRequest # Renamed to avoid conflict with fastapi.Request
from starlette.datastructures import UploadFile as StarletteUploadFile # Renamed to avoid conflict with fastapi.UploadFile
from supabase import create_client, Client, ClientOptions
import uuid
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel

from PIL import Image, ImageDraw, ImageFont
import imageio
import numpy as np
from playwright.async_api import async_playwright
import phonenumbers
from phonenumbers import PhoneNumberMatcher, PhoneNumberFormat, is_valid_number, format_number
import concurrent.futures
import functools
import httpx # Added for proxy

# Create a process pool for heavy CPU/IO tasks
executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

# Import database and models
import database
import models
import auth

# Create necessary directories
os.makedirs("screenshots", exist_ok=True)
os.makedirs("videos", exist_ok=True)
os.makedirs("static", exist_ok=True)
os.makedirs("temp_frames", exist_ok=True)
os.makedirs("templates", exist_ok=True)
os.makedirs("diffs", exist_ok=True)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/screenshots", StaticFiles(directory="screenshots"), name="screenshots")
app.mount("/videos", StaticFiles(directory="videos"), name="videos")
app.mount("/diffs", StaticFiles(directory="diffs"), name="diffs")

templates = Jinja2Templates(directory="templates")

# ========== CUSTOM JINJA2 FILTERS ==========
import json

def from_json(value):
    """Custom Jinja2 filter to parse JSON strings"""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except:
            return []
    return value

# Add custom filters to Jinja2 environment
templates.env.filters['from_json'] = from_json

def to_json(value):
    """Custom Jinja2 filter to convert to JSON string"""
    return json.dumps(value)

templates.env.filters['to_json'] = to_json
# ===========================================

# Create database tables
models.Base.metadata.create_all(bind=database.engine)

# Global dictionary to track running tasks
running_tasks = {}

# Pydantic models for JSON requests
class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    email: str
    username: str
    password: str

# ========== AUTHENTICATION MIDDLEWARE ==========

async def get_current_user_from_cookie(request: Request, db: Session = Depends(auth.get_db)):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        # Use the verify_token function from auth.py
        user_id = auth.verify_token(token)
        if not user_id:
            return None
        
        # Get user from database - ID is now String (UUID)
        user = db.query(models.User).filter(models.User.id == user_id).first()
        return user
    except Exception as e:
        print(f"Authentication error: {e}")
        return None

# ========== AUTHENTICATION DEPENDENCY ==========

async def require_auth(request: Request, db: Session = Depends(auth.get_db)):
    """Dependency to require authentication for protected routes."""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"}
        )
    
    # Enable RLS for this request
    auth.set_db_session_user(db, user.id)
    
    return user

# ========== UNIQUE FILENAME FUNCTION ==========

def get_unique_filename(url: str) -> str:
    """Generate unique filename using last path segment + domain"""
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.replace("www.", "")
    domain = re.sub(r'[^\w\.-]', '-', domain)
    
    path = parsed.path.strip("/")
    if not path or path in ("", "/"):
        page_name = "home"
    else:
        segments = [s for s in path.split("/") if s]
        if segments:
            page_name = segments[-1].split('.')[0]
            page_name = re.sub(r'[^\w\-]', '-', page_name).strip("-").lower()
            if not page_name or page_name in ("index", "home"):
                page_name = "home"
            if len(page_name) > 50:
                page_name = page_name[:47] + "..."
        else:
            page_name = "home"
    
    return f"{page_name}__{domain}"

# ========== STATIC AUDIT FUNCTIONS ==========

# ========== STATIC AUDIT FUNCTIONS ==========

async def capture_screenshots(urls: List[str], browsers: List[str], resolutions: List[Tuple[int, int]], session_id: str, user_id: int, db: Session, access_token: str = None):
    session_folder = f"screenshots/{session_id}"
    os.makedirs(session_folder, exist_ok=True)
    
    # Init Supabase Client with User context if token exists
    sb = None
    if access_token:
        try:
             # Pass access token in header for RLS
             sb = create_client(auth.SUPABASE_URL, auth.SUPABASE_KEY, options=ClientOptions(headers={"Authorization": f"Bearer {access_token}"}))
        except:
             # Fallback or log
             print("Failed to init Supabase client with token")
             pass
    config = { # This config dictionary was misplaced in the original code, moving it here.
        "urls": urls,
        "browsers": browsers,
        "resolutions": [f"{w}x{h}" for w, h in resolutions],
        "type": "static"
    }
    with open(f"{session_folder}/config.json", "w") as f:
        json.dump(config, f)

    try:
        async with async_playwright() as p:
            browser_map = {
                "Chrome": p.chromium,
                "Edge": p.chromium,
                "Firefox": p.firefox,
                "Safari": p.webkit
            }

            # AGGRESSIVE OPTIMIZATION: 5 URLs in parallel
            sem = asyncio.Semaphore(5)

            async def process_url(page, url, w, h, browser_name):
                unique = get_unique_filename(url)
                
                # Check if task was stopped
                session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                if session and session.status == "stopped":
                    return

                try:
                    await page.set_viewport_size({"width": w, "height": h})
                    
                    # 1. Smarter Navigation (Wait for DOM, then Network Idle with short timeout)
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                        await page.wait_for_load_state("networkidle", timeout=5000) # Fast fail to keep moving
                    except:
                        pass

                    # 2. Optimized Hybrid Scroll (Lazy Load Trigger)
                    # Scrolls 1000px steps, stops if hits bottom. Fast.
                    await page.evaluate("""async () => {
                        await new Promise((resolve) => {
                            let totalHeight = 0;
                            const distance = 1000;
                            const timer = setInterval(() => {
                                const scrollHeight = document.body.scrollHeight;
                                window.scrollBy(0, distance);
                                totalHeight += distance;
                                if(totalHeight >= scrollHeight - window.innerHeight){
                                    clearInterval(timer);
                                    resolve();
                                }
                            }, 50); // Very fast scroll
                        });
                    }""")
                    
                    await page.wait_for_timeout(1000) # Short buffer
                    await page.evaluate("() => window.scrollTo(0, 0)")
                    await page.wait_for_timeout(500)

                    path = f"{session_folder}/{browser_name}/{unique}__{w}x{h}.png"
                    await page.screenshot(path=path, full_page=True)
                    
                    # Offload image processing (keep usage of original path for worker if needed, 
                    # but here we just optimize for upload/storage. 
                    # Worker `add_browser_frame` might expect PNG? 
                    # Let's check `add_browser_frame`. It opens image. Pillow opens webp fine.
                    # But we'll optimize AFTER capturing and BEFORE uploading.
                    
                    # OPTIMIZE: Convert to WebP
                    upload_path = path
                    upload_filename = os.path.basename(path)
                    content_type = "image/png"
                    
                    try:
                        webp_path = path.replace(".png", ".webp")
                        with Image.open(path) as img:
                            img.save(webp_path, "WEBP", quality=80, optimize=True)
                        
                        # Verify it saved
                        if os.path.exists(webp_path):
                            # Remove original PNG to save space
                            os.remove(path)
                            upload_path = webp_path
                            upload_filename = os.path.basename(webp_path)
                            content_type = "image/webp"
                    except Exception as opt_err:
                        print(f"Image Optimization Failed: {opt_err}")
                        # Fallback to PNG (path)

                    # Offload image processing (async worker)
                    loop = asyncio.get_running_loop()
                    # Updated to pass upload_path which might be WebP
                    await loop.run_in_executor(executor, add_browser_frame, upload_path, url)

                    # Update progress in database - Best effort
                    try:
                        # Upload to Supabase if client available
                        screenshot_path = upload_path.replace("\\", "/") # Default to local
                        
                        if sb:
                            try:
                                remote_path = f"static/{session_id}/{browser_name}/{os.path.basename(path)}"
                                with open(path, "rb") as f:
                                    sb.storage.from_("screenshots").upload(remote_path, f, {"content-type": "image/png", "upsert": "true"})
                                
                                screenshot_path = sb.storage.from_("screenshots").get_public_url(remote_path)
                                
                                # Clean up local optimized file
                                os.remove(upload_path)
                            except Exception as up_err:
                                print(f"Upload Failed: {up_err}")
                                # Fallback to local path
                        
                        # Save result
                        result_record = models.StaticAuditResult(
                            session_id=session_id,
                            url=url,
                            browser=browser_name,
                            resolution=f"{w}x{h}",
                            screenshot_path=screenshot_path,
                            filename=upload_filename # Store optimized filename
                        )
                        db.add(result_record)
                        
                        session.completed += 1
                        db.commit()
                    except:
                        db.rollback()

                    print(f"[STATIC][{browser_name}] {url} @ {w}x{h} — DONE")
                    
                except Exception as e:
                    print(f"[STATIC][{browser_name}] FAILED {url} @ {w}x{h}: {e}")

            async def run_browser(browser_name: str):
                os.makedirs(f"{session_folder}/{browser_name}", exist_ok=True)
                launch_args = {"headless": True}
                
                if browser_name == "Chrome":
                    launch_args["channel"] = "chrome"
                elif browser_name == "Edge":
                    launch_args["channel"] = "msedge"

                browser = await browser_map[browser_name].launch(**launch_args)
                context = await browser.new_context()
                
                tasks = []
                # Create a worker function to manage page lifecycle
                async def worker(url, w, h):
                    async with sem:
                        try:
                            page = await context.new_page()
                            await process_url(page, url, w, h, browser_name)
                            await page.close()
                        except Exception as e:
                            print(f"Worker error: {e}")

                for url in urls:
                    for w, h in resolutions:
                         tasks.append(worker(url, w, h))
                
                await asyncio.gather(*tasks)
                await context.close()
                await browser.close()

            await asyncio.gather(*[run_browser(b) for b in browsers])
            
        # Mark as completed
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "completed"
            session.completed_at = datetime.utcnow()
            db.commit()
            
    except Exception as e:
        print(f"Static audit error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            db.commit()
    
    # Clean up running tasks
    if session_id in running_tasks:
        del running_tasks[session_id]
        
    print(f"STATIC SESSION {session_id} COMPLETED")

# ========== DYNAMIC AUDIT FUNCTIONS ==========

async def record_videos_async(urls: List[str], selected_browsers: List[str], 
                              selected_resolutions: List[Tuple[int, int]], 
                              session_id: str, user_id: int, db: Session, access_token: str = None):
    session_folder = f"videos/{session_id}"
    os.makedirs(session_folder, exist_ok=True)

    with open(f"{session_folder}/config.json", "w") as f:
        json.dump({
            "urls": urls,
            "browsers": selected_browsers,
            "resolutions": [f"{w}x{h}" for w, h in selected_resolutions],
            "type": "dynamic"
        }, f)

    try:
        async with async_playwright() as p:
            browser_map = {"Chrome": p.chromium, "Edge": p.chromium}

            # AGGRESSIVE OPTIMIZATION: 3 Videos in parallel (High cpu load)
            sem = asyncio.Semaphore(3)
            
            async def process_video(page, url, w, h, browser_name, unique_name):
                 # Check if task was stopped
                session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                if session and session.status == "stopped":
                    return

                try:
                    video_path_local = await record_fullpage_video(page, url, w, h, session_folder, browser_name, unique_name)
                    
                    # Upload to Supabase
                    video_url = video_path_local.replace("\\", "/") # Fallback
                    
                    if access_token:
                        print(f"[DYNAMIC] Access Token present. Attempting upload...")
                        try:
                             sb = create_client(auth.SUPABASE_URL, auth.SUPABASE_KEY, options=ClientOptions(headers={"Authorization": f"Bearer {access_token}"}))
                             
                             remote_path = f"videos/{session_id}/{browser_name}/{os.path.basename(video_path_local)}"
                             print(f"[DYNAMIC] Uploading to: {remote_path}")
                             with open(video_path_local, "rb") as vf:
                                 # videos/mp4 content type
                                 sb.storage.from_("screenshots").upload(remote_path, vf, {"content-type": "video/mp4", "upsert": "true"})
                             
                             video_url = sb.storage.from_("screenshots").get_public_url(remote_path)
                             print(f"[DYNAMIC] Upload Success. URL: {video_url}")
                             
                             # Clean up local
                             if os.path.exists(video_path_local):
                                 os.remove(video_path_local)
                        except Exception as up_err:
                            print(f"[DYNAMIC] Upload Error: {up_err}")
                            import traceback
                            traceback.print_exc()

                    print(f"[DYNAMIC] Final Video URL: {video_url}")
                    # Save result to DB
                    result = models.DynamicAuditResult(
                        session_id=session_id,
                        url=url,
                        browser=browser_name,
                        resolution=f"{w}x{h}",
                        video_path=video_url,
                        filename=os.path.basename(video_path_local)
                    )
                    db.add(result)

                    # Update progress in database - Best effort
                    try:
                        session.completed += 1
                        db.commit()
                    except:
                        db.rollback()
                            
                except Exception as e:
                    print(f"[DYNAMIC][{browser_name}] ERROR: {url} @ {w}x{h} → {e}")

            async def run_browser(browser_name: str):
                os.makedirs(f"{session_folder}/{browser_name}", exist_ok=True)
                browser = await browser_map[browser_name].launch(headless=True)
                
                # Create context
                context = await browser.new_context()
                
                tasks = []
                async def worker(url, w, h):
                    async with sem:
                        try:
                            page = await context.new_page()
                            unique_name = get_unique_filename(url)
                            await process_video(page, url, w, h, browser_name, unique_name)
                            await page.close()
                        except:
                            pass

                for url in urls:
                    for w, h in selected_resolutions:
                        tasks.append(worker(url, w, h))
                
                await asyncio.gather(*tasks)
                await context.close()
                await browser.close()

            await asyncio.gather(*[run_browser(name) for name in selected_browsers if name in browser_map])
            
        # Mark as completed
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "completed"
            session.completed_at = datetime.utcnow()
            db.commit()
            
    except Exception as e:
        print(f"Dynamic audit error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            db.commit()
    
    # Clean up running tasks
    if session_id in running_tasks:
        del running_tasks[session_id]
        
    print(f"DYNAMIC SESSION {session_id} COMPLETED")

async def record_fullpage_video(page, url: str, w: int, h: int, session_folder: str, browser_name: str, unique_name: str):
    """Record a full-page video with scrolling and mouse movement."""
    try:
        await page.set_viewport_size({"width": w, "height": h})
        
        # 1. Smarter Navigation
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_load_state("networkidle", timeout=10000)
        except:
             pass 
        
        # Short stabilization
        await asyncio.sleep(1.0)
        
        # Get page height for scrolling
        page_height = await page.evaluate("document.body.scrollHeight")
        viewport_height = h
        
        # Optimized Scroll Steps: Larger steps, faster
        step_size = int(viewport_height * 0.9) 
        scroll_steps = max(1, page_height // step_size)
        
        frames_dir = f"temp_frames/{unique_name}_{browser_name}_{w}x{h}"
        os.makedirs(frames_dir, exist_ok=True)
        
        frame_count = 0
        
        # Record initial view
        await page.screenshot(path=f"{frames_dir}/frame_{frame_count:04d}.png")
        frame_count += 1
        
        # Simulate scrolling
        current_scroll = 0
        for step in range(scroll_steps + 1): 
            current_scroll += step_size
            if current_scroll > page_height:
                current_scroll = page_height
                
            await page.evaluate(f"window.scrollTo(0, {current_scroll})")
            
            # Very fast wait
            await asyncio.sleep(0.2)
            
            # Simple mouse wiggle
            mouse_x = random.randint(100, w - 100)
            mouse_y = random.randint(100, viewport_height - 100)
            await page.mouse.move(mouse_x, mouse_y)
            # No extra sleep, just capture
            
            # Take screenshot
            await page.screenshot(path=f"{frames_dir}/frame_{frame_count:04d}.png")
            frame_count += 1
            
            if current_scroll >= page_height:
                break
        
        # Scroll back to top
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.5)
        await page.screenshot(path=f"{frames_dir}/frame_{frame_count:04d}.png")
        frame_count += 1
        
        # Create video from frames
        video_path = f"{session_folder}/{browser_name}/{unique_name}__{w}x{h}.mp4"
        os.makedirs(os.path.dirname(video_path), exist_ok=True)
        
        # Use imageio to create video
        images = []
        for i in range(frame_count):
            img_path = f"{frames_dir}/frame_{i:04d}.png"
            if os.path.exists(img_path):
                images.append(imageio.imread(img_path))
        
        if images:
            # Offload video generation to thread pool
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                executor,
                functools.partial(imageio.mimsave, video_path, images, fps=3) # Higher FPS for smoother look
            )
            print(f"Video saved: {video_path}")
            return video_path
        return None
        
        # Clean up temp frames
        shutil.rmtree(frames_dir, ignore_errors=True)
        
    except Exception as e:
        print(f"Error recording video for {url}: {e}")
        raise

# ========== H1 AUDIT FUNCTIONS ==========

async def audit_h1_tags(urls: List[str], session_id: str, user_id: int, db: Session):
    """Audit H1 tags on multiple URLs"""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            
            for i, url in enumerate(urls):
                try:
                    # Check if task was stopped
                    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session and session.status == "stopped":
                        break
                    
                    await page.goto(url, wait_until="networkidle", timeout=90000)
                    await asyncio.sleep(2)  # Wait for page to load
                    
                    # Extract H1 tags
                    h1_elements = await page.evaluate('''() => {
                        const h1s = Array.from(document.querySelectorAll('h1'));
                        return h1s.map(h1 => ({
                            text: h1.textContent.trim(),
                            length: h1.textContent.trim().length
                        }));
                    }''')
                    
                    h1_count = len(h1_elements)
                    h1_texts = [h1['text'] for h1 in h1_elements if h1['text']]
                    issues = []
                    
                    # Analyze H1 tags
                    if h1_count == 0:
                        issues.append("No H1 tag found")
                    elif h1_count > 1:
                        issues.append(f"Multiple H1 tags found ({h1_count})")
                    
                    for h1 in h1_elements:
                        if h1['text']:
                            if h1['length'] > 70:
                                issues.append(f"H1 too long ({h1['length']} chars): '{h1['text'][:50]}...'")
                            if h1['length'] < 20:
                                issues.append(f"H1 too short ({h1['length']} chars): '{h1['text']}'")
                        else:
                            issues.append("Empty H1 tag text")
                    
                    # Save result to database
                    result = models.H1AuditResult(
                        session_id=session_id,
                        url=url,
                        h1_count=h1_count,
                        h1_texts=json.dumps(h1_texts),
                        issues=json.dumps(issues)
                    )
                    db.add(result)
                    
                    # Update progress
                    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session:
                        session.completed += 1
                        db.commit()
                    
                    print(f"[H1 AUDIT] {url} - {h1_count} H1 tag(s)")
                    
                except Exception as e:
                    print(f"[H1 AUDIT] FAILED {url}: {e}")
                    # Save error result
                    result = models.H1AuditResult(
                        session_id=session_id,
                        url=url,
                        h1_count=0,
                        h1_texts=json.dumps([]),
                        issues=json.dumps([f"Error: {str(e)[:100]}"])
                    )
                    db.add(result)
                    
                    # Update progress even on error
                    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session:
                        session.completed += 1
                        db.commit()
            
            await context.close()
            await browser.close()
            
        # Mark as completed
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "completed"
            session.completed_at = datetime.utcnow()
            db.commit()
            
    except Exception as e:
        print(f"H1 audit error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            db.commit()
    
    print(f"H1 AUDIT SESSION {session_id} COMPLETED")

# ========== PHONE NUMBER AUDIT FUNCTIONS ==========

async def audit_phone_numbers(urls: List[str], countries: List[str], options: List[str], 
                              session_id: str, user_id: int, db: Session):
    """Audit phone numbers on multiple URLs"""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            
            # Define regex patterns for different countries
            country_patterns = {
                "US": [r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}'],
                "UK": [r'\+44\s?\d{4}\s?\d{6}', r'0\d{4}\s?\d{6}', r'\(0\d{4}\)\s?\d{6}'],
                "CA": [r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'],
                "AU": [r'\+61\s?\d\s?\d{4}\s?\d{4}', r'0\d\s?\d{4}\s?\d{4}'],
                "DE": [r'\+49\s?\d{5,15}', r'0\d{5,15}'],
                "FR": [r'\+33\s?\d{9}', r'0\d{9}'],
                "JP": [r'\+81\s?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{4}'],
                "IN": [r'\+91\s?\d{5}\s?\d{5}', r'0\d{5}\s?\d{5}']
            }
            
            for i, url in enumerate(urls):
                try:
                    # Check if task was stopped
                    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session and session.status == "stopped":
                        break
                    
                    await page.goto(url, wait_until="networkidle", timeout=90000)
                    await asyncio.sleep(2)  # Wait for page to load
                    
                    # Extract phone numbers with location context
                    found_numbers = await page.evaluate(r'''(patterns) => {
                        const results = [];
                        
                        function getTextNodes(node) {
                            const textNodes = [];
                            if (node.nodeType === 3) {
                                textNodes.push(node);
                            } else {
                                const children = node.childNodes;
                                for (let i = 0; i < children.length; i++) {
                                    textNodes.push(...getTextNodes(children[i]));
                                }
                            }
                            return textNodes;
                        }

                        function getLocation(node) {
                            let current = node;
                            while (current && current.nodeType === 1) { // Element node
                                const tagName = current.tagName.toLowerCase();
                                if (tagName === 'header') return 'Header';
                                if (tagName === 'footer') return 'Footer';
                                current = current.parentElement;
                            }
                            // Check ancestors
                            current = node.parentElement;
                            while (current) {
                                if (current.tagName) {
                                    const tagName = current.tagName.toLowerCase();
                                    if (tagName === 'header') return 'Header';
                                    if (tagName === 'footer') return 'Footer';
                                }
                                current = current.parentElement;
                            }
                            return 'Body';
                        }
                        
                        // Scan all text nodes
                        const body = document.body;
                        const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT, null, false);
                        
                        let node;
                        while (node = walker.nextNode()) {
                            const text = node.textContent;
                            if (!text || text.trim().length < 5) continue;
                            
                            // Check against all country patterns
                            for (const [country, country_patterns] of Object.entries(patterns)) {
                                for (const pattern of country_patterns) {
                                    // Convert python regex slightly if needed or use simple regex
                                    // For simplicity, we'll send regex strings that work in JS
                                    try {
                                        // Simple approximation for demo: finding numbers
                                        // Real implementation would pass simpler regexes
                                        const regex = new RegExp(pattern.replace(/\(\?<!\\d\)/g, '').replace(/\(?!\d\)/g, ''), 'g'); // Strip lookbehinds if any
                                        
                                        let match;
                                        while ((match = regex.exec(text)) !== null) {
                                            const number = match[0].trim();
                                            const location = getLocation(node);
                                            
                                            // Avoid duplicates in results if possible
                                            const exists = results.find(r => r.number === number);
                                            if (!exists) {
                                                results.push({ number, location, source: 'text' });
                                            }
                                        }
                                    } catch (e) {
                                        // Ignore regex errors
                                    }
                                }
                            }
                        }
                        
                        return results;
                    }''', country_patterns)
                    
                    # Simplify: Playwright JS regex is limited compared to Python's.
                    # APPROACH 2: Hybrid
                    # 1. Get text content of specific regions
                    regions_text = await page.evaluate('''() => {
                        const getRegionText = (selector) => {
                            const els = document.querySelectorAll(selector);
                            let text = "";
                            els.forEach(el => text += " " + el.innerText);
                            return text;
                        };
                        
                        return {
                            header: getRegionText('header'),
                            footer: getRegionText('footer'),
                            body: document.body.innerText
                        };
                    }''')
                    
                    phone_numbers_data = [] # List of dicts: {number, location}
                    seen_numbers = set()
                    issues = []
                    formats_detected = set()
                    
                    # Process regions
                    for region_name, content in regions_text.items():
                        location_label = region_name.capitalize()
                        if not content: continue
                        
                        for country in countries:
                            if country in country_patterns:
                                for pattern in country_patterns[country]:
                                    import re
                                    matches = re.finditer(pattern, content)
                                    for match in matches:
                                        phone_number = match.group().strip()
                                        
                                        # Deduplicate globally? or per location? 
                                        # Let's deduplicate globally but prefer Header/Footer location if found there
                                        if phone_number not in seen_numbers:
                                            seen_numbers.add(phone_number)
                                            phone_numbers_data.append({
                                                "number": phone_number,
                                                "location": location_label if location_label in ["Header", "Footer"] else "Body"
                                            })
                                            formats_detected.add(country)
                                        else:
                                            # If already found in Body but now finding in Header/Footer, update it
                                            if location_label in ["Header", "Footer"]:
                                                for item in phone_numbers_data:
                                                    if item["number"] == phone_number and item["location"] == "Body":
                                                        item["location"] = location_label
                                                        break
                    
                    # Check clickable links (separate check)
                    if "clickable" in options:
                        tel_links = await page.evaluate('''() => {
                            const links = Array.from(document.querySelectorAll('a[href^="tel:"]'));
                            return links.map(link => {
                                // Determine origin
                                let origin = 'Body';
                                if (link.closest('header')) origin = 'Header';
                                if (link.closest('footer')) origin = 'Footer';
                                
                                return {
                                    number: link.href.replace('tel:', '').trim(),
                                    location: origin
                                };
                            });
                        }''')
                        
                        for link in tel_links:
                            p_num = link["number"]
                            p_loc = link["location"]
                            
                            if p_num and p_num not in seen_numbers:
                                seen_numbers.add(p_num)
                                phone_numbers_data.append({
                                    "number": p_num,
                                    "location": p_loc
                                })
                                issues.append("Click-to-call link found")
                            elif p_num:
                                 # Update location if better
                                 if p_loc in ["Header", "Footer"]:
                                     for item in phone_numbers_data:
                                         if item["number"] == p_num and item["location"] == "Body":
                                             item["location"] = p_loc
                                             break

                    # Check schema
                    if "schema" in options:
                         schema_phones = await page.evaluate('''() => {
                            const schemas = Array.from(document.querySelectorAll('[itemtype*="Organization"], [itemtype*="LocalBusiness"]'));
                            const phones = [];
                            schemas.forEach(schema => {
                                const phoneEl = schema.querySelector('[itemprop="telephone"]');
                                if (phoneEl) {
                                    phones.push(phoneEl.textContent.trim());
                                }
                            });
                            return phones;
                        }''')
                         
                         for schema_phone in schema_phones:
                             if schema_phone and schema_phone not in seen_numbers:
                                 seen_numbers.add(schema_phone)
                                 phone_numbers_data.append({
                                     "number": schema_phone,
                                     "location": "Schema"
                                 })
                                 formats_detected.add("schema")

                    # Validate (using stored numbers)
                    if "validate" in options:
                        for item in phone_numbers_data:
                            phone = item["number"]
                            try:
                                parsed = phonenumbers.parse(phone, None)
                                if not phonenumbers.is_valid_number(parsed):
                                    issues.append(f"Invalid phone number format: {phone}")
                            except:
                                issues.append(f"Poorly formatted phone number: {phone}")

                    # Consistency check
                    if "consistency" in options and i > 0:
                        prev_result = db.query(models.PhoneAuditResult).filter_by(
                             session_id=session_id
                        ).order_by(models.PhoneAuditResult.created_at.desc()).first()
                        
                        if prev_result:
                            try:
                                # Prev result might be old string list OR new dict list
                                prev_data = json.loads(prev_result.phone_numbers)
                                prev_numbers_set = set()
                                if prev_data and isinstance(prev_data[0], dict):
                                    prev_numbers_set = {p["number"] for p in prev_data}
                                else:
                                    prev_numbers_set = set(prev_data)
                                    
                                current_numbers_set = {p["number"] for p in phone_numbers_data}
                                
                                if prev_numbers_set != current_numbers_set:
                                    issues.append("Phone numbers differ from other pages")
                            except:
                                pass

                    # Save result
                    result = models.PhoneAuditResult(
                        session_id=session_id,
                        url=url,
                        phone_numbers=json.dumps(phone_numbers_data), # Now storing dicts
                        phone_count=len(phone_numbers_data),
                        formats_detected=json.dumps(list(formats_detected)),
                        issues=json.dumps(issues)
                    )
                    db.add(result)
                    
                    # Update progress
                    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session:
                        session.completed += 1
                        db.commit()
                    
                    print(f"[PHONE AUDIT] {url} - {len(phone_numbers_data)} phone number(s) found")
                    
                except Exception as e:
                    print(f"[PHONE AUDIT] FAILED {url}: {e}")
                    import traceback
                    traceback.print_exc()
                    
                    # Save error result
                    result = models.PhoneAuditResult(
                        session_id=session_id,
                        url=url,
                        phone_numbers=json.dumps([]),
                        phone_count=0,
                        formats_detected=json.dumps([]),
                        issues=json.dumps([f"Error: {str(e)[:100]}"])
                    )
                    db.add(result)
                    
                    # Update progress
                    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session:
                        session.completed += 1
                        db.commit()
            
            await context.close()
            await browser.close()
            
        # Mark as completed
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "completed"
            session.completed_at = datetime.utcnow()
            db.commit()
            
    except Exception as e:
        print(f"Phone audit error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            db.commit()
    
    print(f"PHONE AUDIT SESSION {session_id} COMPLETED")

# ========== HELPER FUNCTIONS ==========

def add_browser_frame(img_path: str, url: str):
    """Add browser frame with URL bar to screenshot."""
    try:
        img = Image.open(img_path)
        width, height = img.size
        
        # Create new image with frame
        frame_height = 80
        new_height = height + frame_height
        new_img = Image.new('RGB', (width, new_height), color='white')
        
        # Draw browser frame
        draw = ImageDraw.Draw(new_img)
        
        # Browser top bar
        draw.rectangle([(0, 0), (width, 40)], fill='#f1f3f4')
        
        # Browser controls (circles)
        circle_radius = 6
        circle_spacing = 20
        start_x = 20
        
        colors = ['#ff5f56', '#ffbd2e', '#27ca3f']
        for i, color in enumerate(colors):
            x0 = start_x + i * circle_spacing - circle_radius
            y0 = 20 - circle_radius
            x1 = start_x + i * circle_spacing + circle_radius
            y1 = 20 + circle_radius
            draw.ellipse([(x0, y0), (x1, y1)], fill=color)
        
        # URL bar
        url_bar_height = 30
        url_bar_y = 45
        draw.rectangle([(60, url_bar_y), (width - 20, url_bar_y + url_bar_height)], 
                      fill='#e8eaed', outline='#dadce0', width=1)
        
        # Add URL text (truncate if too long)
        try:
            font = ImageFont.truetype("arial.ttf", 12)
        except:
            font = ImageFont.load_default()
        
        # Truncate URL if too long
        max_url_width = width - 90
        url_text = url
        bbox = draw.textbbox((0, 0), url_text, font=font)
        text_width = bbox[2] - bbox[0]
        
        if text_width > max_url_width:
            # Truncate with ellipsis
            while text_width > max_url_width and len(url_text) > 10:
                url_text = url_text[:-1]
                bbox = draw.textbbox((0, 0), url_text + "...", font=font)
                text_width = bbox[2] - bbox[0]
            url_text = url_text + "..."
        
        draw.text((70, url_bar_y + 8), url_text, fill='#5f6368', font=font)
        
        # Paste original image below frame
        new_img.paste(img, (0, frame_height))
        
        # Save
        new_img.save(img_path)
        print(f"Added browser frame to: {img_path}")
        
    except Exception as e:
        print(f"Error adding browser frame: {e}")

# ========== BACKGROUND TASKS ==========

def static_audit_task(urls: List[str], browsers: List[str], resolutions: List[str], 
                      session_id: str, user_id: int, session_name: str, access_token: str = None):
    selected_res = [(int(r.split('x')[0]), int(r.split('x')[1])) for r in resolutions]
    
    # Create database session
    db = database.SessionLocal()
    try:
        # Create session record
        session = models.AuditSession(
            session_id=session_id,
            user_id=user_id,
            session_type="static",
            name=session_name,
            urls=json.dumps(urls),
            browsers=json.dumps(browsers),
            resolutions=json.dumps(resolutions),
            total_expected=len(urls) * len(browsers) * len(resolutions),
            status="running"
        )
        db.add(session)
        db.commit()
        
        # Run the audit
        asyncio.run(capture_screenshots(urls, browsers, selected_res, session_id, user_id, db, access_token))
    finally:
        db.close()

def dynamic_audit_task(urls: List[str], browsers: List[str], resolutions: List[str], 
                       session_id: str, user_id: int, session_name: str, access_token: str = None):
    selected_res = [(int(r.split('x')[0]), int(r.split('x')[1])) for r in resolutions]
    
    # Create database session
    db = database.SessionLocal()
    try:
        # Create session record
        session = models.AuditSession(
            session_id=session_id,
            user_id=user_id,
            session_type="dynamic",
            name=session_name,
            urls=json.dumps(urls),
            browsers=json.dumps(browsers),
            resolutions=json.dumps(resolutions),
            total_expected=len(urls) * len([b for b in browsers if b in ["Chrome", "Edge"]]) * len(resolutions),
            status="running"
        )
        db.add(session)
        db.commit()
        
        # Run the audit
        asyncio.run(record_videos_async(urls, browsers, selected_res, session_id, user_id, db, access_token))
    finally:
        db.close()

def h1_audit_task(urls: List[str], session_id: str, user_id: int, session_name: str):
    """Background task for H1 audit"""
    db = database.SessionLocal()
    try:
        # Create session record
        session = models.AuditSession(
            session_id=session_id,
            user_id=user_id,
            session_type="h1",
            name=session_name,
            urls=json.dumps(urls),
            browsers=json.dumps([]),
            resolutions=json.dumps([]),
            total_expected=len(urls),
            status="running"
        )
        db.add(session)
        db.commit()
        
        # Run the audit
        asyncio.run(audit_h1_tags(urls, session_id, user_id, db))
    finally:
        db.close()

def phone_audit_task(urls: List[str], countries: List[str], options: List[str], 
                     session_id: str, user_id: int, session_name: str):
    """Background task for phone audit"""
    db = database.SessionLocal()
    try:
        # Create session record
        session = models.AuditSession(
            session_id=session_id,
            user_id=user_id,
            session_type="phone",
            name=session_name,
            urls=json.dumps(urls),
            browsers=json.dumps([]),
            resolutions=json.dumps([]),
            total_expected=len(urls),
            status="running"
        )
        db.add(session)
        db.commit()
        
        # Run the audit
        asyncio.run(audit_phone_numbers(urls, countries, options, session_id, user_id, db))
    finally:
        db.close()

# ========== ROUTES ==========

@app.get("/")
async def home(request: Request, db: Session = Depends(auth.get_db)):
    """Root route - Landing page for guests, redirect to Dashboard for users"""
    user = await get_current_user_from_cookie(request, db)
    if user:
        # Redirect to new SaaS Dashboard if authenticated
        return RedirectResponse(url="/platform/dashboard", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    
    # Show Marketing Landing Page if not authenticated
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "user": None
    })

@app.get("/dashboard")
async def dashboard(request: Request, user = Depends(require_auth)):
    """Dashboard route - requires authentication"""
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "user": user,
        "show_nav": True
    })

@app.get("/login")
async def login_page(request: Request, db: Session = Depends(auth.get_db)):
    """Login page - redirects to dashboard if already logged in"""
    user = await get_current_user_from_cookie(request, db)
    if user:
        return RedirectResponse(url="/", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("access_token")
    return response

@app.get("/register")
async def register_page(request: Request, db: Session = Depends(auth.get_db)):
    """Register page - redirects to dashboard if already logged in"""
    user = await get_current_user_from_cookie(request, db)
    if user:
        return RedirectResponse(url="/", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    return templates.TemplateResponse("register.html", {"request": request})

@app.get("/profile")
async def profile_page(request: Request, db: Session = Depends(auth.get_db)):
    """Profile page - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
    
    # Get user's sessions
    sessions = db.query(models.AuditSession).filter_by(user_id=user.id).order_by(models.AuditSession.created_at.desc()).all()
    
    # Parse JSON strings
    for session in sessions:
        try:
            session.urls = json.loads(session.urls)
        except:
            session.urls = []
    
    # Calculate stats
    total_sessions = len(sessions)
    completed_sessions = len([s for s in sessions if s.status == "completed"])
    running_sessions = len([s for s in sessions if s.status == "running"])
    static_sessions = len([s for s in sessions if s.session_type == "static"])
    dynamic_sessions = len([s for s in sessions if s.session_type == "dynamic"])
    h1_sessions = len([s for s in sessions if s.session_type == "h1"])
    phone_sessions = len([s for s in sessions if s.session_type == "phone"])
    
    # Pre-calculate progress for each session
    for session in sessions:
        if session.total_expected > 0:
            session.progress_percent = round((session.completed / session.total_expected) * 100, 1)
        else:
            session.progress_percent = 0

    # Calculate percentages for UI
    def calc_pct(part, whole):
        return int(round((part / whole) * 100)) if whole > 0 else 0
        
    pct_completed = calc_pct(completed_sessions, total_sessions)
    pct_running = calc_pct(running_sessions, total_sessions)
    pct_static = calc_pct(static_sessions, total_sessions)
    pct_dynamic = calc_pct(dynamic_sessions, total_sessions)
    pct_h1 = calc_pct(h1_sessions, total_sessions)
    pct_phone = calc_pct(phone_sessions, total_sessions)
    
    return templates.TemplateResponse("profile.html", {
        "request": request,
        "user": user,
        "sessions": sessions,
        "total_sessions": total_sessions,
        "completed_sessions": completed_sessions,
        "running_sessions": running_sessions,
        "static_sessions": static_sessions,
        "dynamic_sessions": dynamic_sessions,
        "h1_sessions": h1_sessions,
        "phone_sessions": phone_sessions,
        "pct_completed": pct_completed,
        "pct_running": pct_running,
        "pct_static": pct_static,
        "pct_dynamic": pct_dynamic,
        "pct_h1": pct_h1,
        "pct_phone": pct_phone
    })

@app.get("/responsive")
async def responsive_page(request: Request, user = Depends(require_auth)):
    """Responsive audit page - requires authentication"""
    return templates.TemplateResponse("responsive.html", {"request": request, "user": user})

@app.get("/responsive/static")
async def static_audit_page(request: Request, user = Depends(require_auth)):
    """Static audit page - requires authentication"""
    return templates.TemplateResponse("static-audit.html", {"request": request, "user": user})

@app.get("/static-results/{session_id}")
async def static_results_view(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """View static audit results - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
        
    session = db.query(models.AuditSession).filter(
        models.AuditSession.session_id == session_id,
        models.AuditSession.user_id == user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    # Parse JSON fields
    try:
        session.urls = json.loads(session.urls)
        session.browsers = json.loads(session.browsers)
        session.resolutions = json.loads(session.resolutions)
    except:
        pass
        
    # Get results from DB
    results = db.query(models.StaticAuditResult).filter_by(session_id=session_id).all()
    
    # Serialize results for JS
    results_list = []
    for r in results:
        results_list.append({
            "url": r.url,
            "browser": r.browser,
            "resolution": r.resolution,
            "filename": r.filename,
            "screenshot_path": r.screenshot_path # Include full path/URL
        })
    
    return templates.TemplateResponse("static-results.html", {
        "request": request,
        "user": user,
        "session": session,
        "results": results,
        "results_data": json.dumps(results_list),
        "results_json": json.dumps([r.url for r in results]), # Helper if needed
    })

@app.get("/dynamic-results/{session_id}")
async def dynamic_results_view(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """View dynamic audit results - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
        
    session = db.query(models.AuditSession).filter(
        models.AuditSession.session_id == session_id,
        models.AuditSession.user_id == user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Parse JSON fields
    try:
        if isinstance(session.urls, str):
            session.urls = json.loads(session.urls)
    except:
        session.urls = []

    try:
        if isinstance(session.browsers, str):
            session.browsers = json.loads(session.browsers)
    except:
        session.browsers = []

    try:
        if isinstance(session.resolutions, str):
            session.resolutions = json.loads(session.resolutions)
    except:
        session.resolutions = []

    # Get results from DB
    results = db.query(models.DynamicAuditResult).filter_by(session_id=session_id).all()
    
    # Serialize results for JS
    results_list = []
    for r in results:
        results_list.append({
            "url": r.url,
            "browser": r.browser,
            "resolution": r.resolution,
            "video_path": r.video_path,
            "filename": r.filename
        })

    return templates.TemplateResponse("dynamic-results.html", {
        "request": request,
        "user": user,
        "session": session,
        "results": results, # Keep for backward compatibility if needed, though we use results_json now
        "results_json": json.dumps(results_list), 
    })

@app.get("/responsive/dynamic")
async def dynamic_audit_page(request: Request, user = Depends(require_auth)):
    """Dynamic audit page - requires authentication"""
    return templates.TemplateResponse("dynamic-audit.html", {"request": request, "user": user})

@app.get("/h1-audit")
async def h1_audit_page(request: Request, user = Depends(require_auth)):
    """H1 audit page - requires authentication"""
    return templates.TemplateResponse("h1-audit.html", {"request": request, "user": user})

@app.get("/phone-audit")
async def phone_audit_page(request: Request, user = Depends(require_auth)):
    """Phone audit page - requires authentication"""
    return templates.TemplateResponse("phone-audit.html", {"request": request, "user": user})

# ========== API ROUTES ==========

@app.post("/api/auth/register")
async def register(
    request: RegisterRequest, 
    db: Session = Depends(auth.get_db)
):
    """Register new user using Supabase Auth"""
    try:
        # Check if username exists locally first (optional optimization)
        if db.query(models.User).filter(models.User.username == request.username).first():
            raise HTTPException(status_code=400, detail="Username already taken")

        # Register with Supabase (handles email uniqueness)
        user = auth.register_user(request.email, request.password, request.username, db)

        print(f"User created successfully: {user.id}, {user.username}")

        # Auto-login to get token
        session = auth.login_user(request.email, request.password)

        return {
            "access_token": session.access_token,
            "token_type": "bearer",
            "user": {"id": user.id, "username": user.username}
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Registration error: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")

@app.post("/api/auth/login")
async def login(
    request: LoginRequest,  # Accept JSON request
    db: Session = Depends(auth.get_db)
):
    """Login user via Supabase and return access token"""
    print(f"Login attempt: {request.username}")
    
    try:
        # Supabase Login (requires email, but we support username login via lookup)
        email = request.username
        if "@" not in email:
            # Lookup email by username if username provided
            user = db.query(models.User).filter(models.User.username == request.username).first()
            if not user:
                 raise HTTPException(status_code=400, detail="Incorrect username or password")
            email = user.email

        # Authenticate with Supabase
        session = auth.login_user(email, request.password)
        
        # Get local profile to return username
        user = db.query(models.User).filter(models.User.id == session.user.id).first()
        username = user.username if user else email.split("@")[0]

        return {
            "access_token": session.access_token, 
            "token_type": "bearer", 
            "user": {"id": session.user.id, "username": username}
        }
    except Exception as e:
        print(f"Login error: {e}")
        raise HTTPException(status_code=400, detail="Incorrect username or password")

@app.post("/api/auth/logout")
async def logout():
    """Logout user by clearing cookie"""
    response = JSONResponse({"message": "Logged out successfully"})
    response.delete_cookie(key="access_token")
    return response

# ========== PASSWORD RESET MODELS ==========

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    password: str

# ========== PASSWORD RESET ENDPOINTS ==========

@app.get("/forgot-password")
async def forgot_password_page(request: Request):
    """Render forgot password page"""
    return templates.TemplateResponse("forgot-password.html", {"request": request})

@app.post("/api/auth/forgot-password")
async def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(auth.get_db)):
    """Generate password reset token"""
    # Find user by email
    user = db.query(models.User).filter(models.User.email == request.email).first()
    
    if not user:
        # Don't reveal if email exists for security
        return JSONResponse({
            "message": "If the email exists, a reset link has been sent.",
            "reset_link": None
        })
    
    # Generate unique token
    import secrets
    token = secrets.token_urlsafe(32)
    
    # Set expiration (30 minutes from now)
    expires_at = datetime.utcnow() + timedelta(minutes=30)
    
    # Create reset token record
    reset_token = models.PasswordResetToken(
        user_id=user.id,
        token=token,
        expires_at=expires_at
    )
    db.add(reset_token)
    db.commit()
    
    # For development: return the reset link
    reset_link = f"http://127.0.0.1:8000/reset-password/{token}"
    
    return JSONResponse({
        "message": "Password reset link generated successfully!",
        "reset_link": reset_link  # In production, this would be sent via email
    })

@app.get("/reset-password/{token}")
async def reset_password_page(token: str, request: Request, db: Session = Depends(auth.get_db)):
    """Render reset password page with token validation"""
    # Validate token exists and is not expired
    reset_token = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.token == token,
        models.PasswordResetToken.used == False,
        models.PasswordResetToken.expires_at > datetime.utcnow()
    ).first()
    
    if not reset_token:
        # Token invalid, expired, or already used
        return templates.TemplateResponse("reset-password.html", {
            "request": request,
            "token": token,
            "error": "Invalid or expired reset token"
        })
    
    return templates.TemplateResponse("reset-password.html", {
        "request": request,
        "token": token
    })

@app.post("/api/auth/reset-password")
async def reset_password(request: ResetPasswordRequest, db: Session = Depends(auth.get_db)):
    """Reset user password with valid token"""
    # Validate token
    reset_token = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.token == request.token,
        models.PasswordResetToken.used == False,
        models.PasswordResetToken.expires_at > datetime.utcnow()
    ).first()
    
    if not reset_token:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    
    # Validate password
    if len(request.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    
    # Get user
    user = db.query(models.User).filter(models.User.id == reset_token.user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Update password
    user.hashed_password = auth.get_password_hash(request.password)
    
    # Mark token as used
    reset_token.used = True
    
    db.commit()
    
    return JSONResponse({
        "message": "Password reset successfully! Redirecting to login..."
    })

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """Delete audit session and associated data"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
         raise HTTPException(status_code=401, detail="Not authenticated")
         
    session = db.query(models.AuditSession).filter(
        models.AuditSession.session_id == session_id,
        models.AuditSession.user_id == user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
def perform_session_cleanup(session_id: str, db: Session):
    """Helper to cleanup session artifacts and DB records (Child records only)"""
    try:
        # Manual Cascade Delete
        db.query(models.StaticAuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.DynamicAuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.UnifiedAuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.VisualAuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.PerformanceAuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.AccessibilityAuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.H1AuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.PhoneAuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
    except Exception as e:
        print(f"Cleanup Error DB {session_id}: {e}")
        # Ensure we don't rollback here, allow caller to handle transaction
        # But querying and deleting in same transaction reference is fine.

    # Clean up Files (Best effort)
    folders = [
        f"screenshots/{session_id}",
        f"videos/{session_id}",
        f"diffs/{session_id}"
    ]
    for folder in folders:
        if os.path.exists(folder):
            try:
                shutil.rmtree(folder)
            except Exception as e:
                print(f"Error deleting folder {folder}: {e}")

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """Delete audit session and associated data"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
         raise HTTPException(status_code=401, detail="Not authenticated")
         
    session = db.query(models.AuditSession).filter(
        models.AuditSession.session_id == session_id,
        models.AuditSession.user_id == user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    try:
        perform_session_cleanup(session_id, db)
        
        # Delete Session
        db.delete(session)
        db.commit()
        
        return JSONResponse({"message": "Session deleted"})
        
    except Exception as e:
        db.rollback()
        print(f"Delete Error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete session: {str(e)}")

@app.delete("/api/sessions")
async def clear_all_sessions(request: Request, db: Session = Depends(auth.get_db)):
    """Delete ALL audit sessions for the user"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
         raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Get all sessions
    sessions = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id).all()
    count = len(sessions)
    deleted = 0
    
    for session in sessions:
        try:
            perform_session_cleanup(session.session_id, db)
            db.delete(session)
            db.commit()
            deleted += 1
        except Exception as e:
            db.rollback()
            print(f"Failed to clear session {session.session_id}: {e}")
            
    return JSONResponse({"message": f"History cleared. Deleted {deleted}/{count} sessions."})

@app.post("/upload/static")
async def upload_static(
    request: Request,
    file: UploadFile = File(...),
    browsers: str = Form(...),
    resolutions: str = Form(...),
    session_name: str = Form("My Static Audit"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(auth.get_db)
):
    """Upload URLs for static audit - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    content = await file.read()
    text_content = content.decode("utf-8", errors="ignore")
    urls = [line.strip() for line in text_content.splitlines() if line.strip().startswith(("http://", "https://"))]

    if not urls:
        return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    selected_browsers = json.loads(browsers)
    selected_resolutions = json.loads(resolutions)

    if not selected_browsers or not selected_resolutions:
        return JSONResponse({"error": "Select at least one browser and resolution"}, status_code=400)

    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    total_expected = len(urls) * len(selected_browsers) * len(selected_resolutions)
    
    token = request.cookies.get("access_token")

    # Start background task
    background_tasks.add_task(static_audit_task, urls, selected_browsers, selected_resolutions, session_id, user.id, session_name, token)
    
    # Store task reference
    running_tasks[session_id] = "static"

    return JSONResponse({
        "session": session_id,
        "total_expected": total_expected,
        "type": "static"
    })

@app.post("/upload/dynamic")
async def upload_dynamic(
    request: Request,
    file: UploadFile = File(...),
    browsers: str = Form(...),
    resolutions: str = Form(...),
    session_name: str = Form("My Dynamic Audit"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(auth.get_db)
):
    """Upload URLs for dynamic audit - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    content = await file.read()
    text_content = content.decode("utf-8", errors="ignore")
    urls = [line.strip() for line in text_content.splitlines() if line.strip().startswith(("http://", "https://"))]

    if not urls:
        return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    selected_browsers = json.loads(browsers)
    selected_resolutions = json.loads(resolutions)

    supported_browsers = [b for b in selected_browsers if b in ["Chrome", "Edge"]]
    if not supported_browsers:
        return JSONResponse({"error": "Select Chrome or Edge for video recording"}, status_code=400)

    if not selected_resolutions:
        return JSONResponse({"error": "Select at least one resolution"}, status_code=400)

    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    total_expected = len(urls) * len(supported_browsers) * len(selected_resolutions)
    
    token = request.cookies.get("access_token")

    # Start background task
    background_tasks.add_task(dynamic_audit_task, urls, supported_browsers, selected_resolutions, session_id, user.id, session_name, token)
    
    # Store task reference
    running_tasks[session_id] = "dynamic"

    return JSONResponse({
        "session": session_id,
        "total_expected": total_expected,
        "type": "dynamic"
    })

@app.post("/upload/h1")
async def upload_h1(
    request: Request,
    file: UploadFile = File(...),
    session_name: str = Form("My H1 Audit"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(auth.get_db)
):
    """Upload URLs for H1 audit - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    content = await file.read()
    text_content = content.decode("utf-8", errors="ignore")
    urls = [line.strip() for line in text_content.splitlines() if line.strip().startswith(("http://", "https://"))]

    if not urls:
        return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Start background task
    background_tasks.add_task(h1_audit_task, urls, session_id, user.id, session_name)
    
    # Store task reference
    running_tasks[session_id] = "h1"

    return JSONResponse({
        "session": session_id,
        "total_expected": len(urls),
        "type": "h1"
    })

@app.post("/upload/phone")
async def upload_phone(
    request: Request,
    file: UploadFile = File(...),
    countries: str = Form("[]"),
    options: str = Form("[]"),
    session_name: str = Form("My Phone Audit"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(auth.get_db)
):
    """Upload URLs for phone audit - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    content = await file.read()
    text_content = content.decode("utf-8", errors="ignore")
    urls = [line.strip() for line in text_content.splitlines() if line.strip().startswith(("http://", "https://"))]

    if not urls:
        return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    selected_countries = json.loads(countries)
    selected_options = json.loads(options)

    if not selected_countries:
        return JSONResponse({"error": "Select at least one country code"}, status_code=400)

    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Start background task
    background_tasks.add_task(phone_audit_task, urls, selected_countries, selected_options, session_id, user.id, session_name)
    
    # Store task reference
    running_tasks[session_id] = "phone"

    return JSONResponse({
        "session": session_id,
        "total_expected": len(urls),
        "type": "phone"
    })

@app.post("/api/sessions/{session_id}/stop")
async def stop_session(
    session_id: str,
    request: Request,
    db: Session = Depends(auth.get_db)
):
    """Stop a running session - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Find session
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Update status
    session.status = "stopped"
    db.commit()
    
    return {"message": "Session stopped successfully"}

@app.delete("/api/sessions/{session_id}")
async def delete_session(
    session_id: str,
    request: Request,
    db: Session = Depends(auth.get_db)
):
    """Delete a session - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Find session
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Delete files
    if session.session_type == "static":
        folder_path = f"screenshots/{session_id}"
    elif session.session_type == "dynamic":
        folder_path = f"videos/{session_id}"
    elif session.session_type == "h1":
        folder_path = f"h1-audits/{session_id}"
    else:
        folder_path = f"phone-audits/{session_id}"
    
    if os.path.exists(folder_path):
        shutil.rmtree(folder_path, ignore_errors=True)
    
    # Delete related audit results
    if session.session_type == "h1":
        results = db.query(models.H1AuditResult).filter_by(session_id=session_id).all()
        for result in results:
            db.delete(result)
    elif session.session_type == "phone":
        results = db.query(models.PhoneAuditResult).filter_by(session_id=session_id).all()
        for result in results:
            db.delete(result)
    
    # Delete database record
    db.delete(session)
    db.commit()
    
    return {"message": "Session deleted successfully"}

@app.delete("/api/sessions")
async def delete_all_sessions(
    request: Request,
    db: Session = Depends(auth.get_db)
):
    """Delete all completed sessions for user"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
        
    sessions = db.query(models.AuditSession).filter(
        models.AuditSession.user_id == user.id,
        models.AuditSession.status == "completed"
    ).all()
    
    deleted_count = 0
    for session in sessions:
        # Delete files
        if session.session_type == "static":
            folder_path = f"screenshots/{session.session_id}"
        elif session.session_type == "dynamic":
            folder_path = f"videos/{session.session_id}"
        elif session.session_type == "h1":
            folder_path = f"h1-audits/{session.session_id}"
        else:
            folder_path = f"phone-audits/{session.session_id}"
        
        if os.path.exists(folder_path):
            shutil.rmtree(folder_path, ignore_errors=True)
            
        # Delete related results
        if session.session_type == "h1":
            try:
                db.query(models.H1AuditResult).filter_by(session_id=session.session_id).delete()
            except: pass
        elif session.session_type == "phone":
             try:
                db.query(models.PhoneAuditResult).filter_by(session_id=session.session_id).delete()
             except: pass
        elif session.session_type == "unified":
             try:
                db.query(models.UnifiedAuditResult).filter_by(session_id=session.session_id).delete()
             except: pass
        elif session.session_type == "accessibility":
             try:
                db.query(models.AccessibilityAuditResult).filter_by(session_id=session.session_id).delete()
             except: pass

        db.delete(session)
        deleted_count += 1
        
    db.commit()
    return {"message": f"Deleted {deleted_count} sessions"}

@app.get("/progress/{session_type}/{session_id}")
async def progress(session_type: str, session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@app.get("/progress/static/{session_id}")
async def static_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a static session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@app.get("/progress/dynamic/{session_id}")
async def dynamic_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a dynamic session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@app.get("/progress/h1/{session_id}")
async def h1_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a H1 audit session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@app.get("/progress/phone/{session_id}")
async def phone_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a phone audit session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@app.get("/session-config/{session_type}/{session_id}")
async def session_config(session_type: str, session_id: str, db: Session = Depends(auth.get_db)):
    """Get session configuration"""
    if session_type == "static":
        path = f"screenshots/{session_id}/config.json"
    elif session_type == "dynamic":
        path = f"videos/{session_id}/config.json"
    else:
        return {"urls": [], "browsers": [], "resolutions": [], "type": session_type}
    
    if not os.path.exists(path):
        return {"urls": [], "browsers": [], "resolutions": [], "type": session_type}
    
    with open(path) as f:
        return json.load(f)

@app.get("/results/{session_type}/{session_id}")
async def view_results(session_type: str, session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """View results of a completed session - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
    
    # Verify ownership
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Check if session is completed
    if session.status != "completed":
        raise HTTPException(status_code=400, detail="Session not completed yet")
    
    # Parse session data
    try:
        session.urls = json.loads(session.urls)
        session.browsers = json.loads(session.browsers)
        session.resolutions = json.loads(session.resolutions)
    except:
        session.urls = []
        session.browsers = []
        session.resolutions = []
    
    # Render appropriate results template
    if session_type == "static":
        return templates.TemplateResponse("static-results.html", {
            "request": request,
            "user": user,
            "session": session,
            "session_id": session_id,
            "session_type": "static"
        })
    elif session_type == "dynamic":
        # Filter browsers to only include Chrome and Edge for dynamic audits
        session.browsers = [b for b in session.browsers if b in ["Chrome", "Edge"]]
        return templates.TemplateResponse("dynamic-results.html", {
            "request": request,
            "user": user,
            "session": session,
            "session_id": session_id,
            "session_type": "dynamic"
        })
    elif session_type == "h1":
        # Get H1 audit results
        h1_results = db.query(models.H1AuditResult).filter_by(session_id=session_id).all()
        
        # Convert results to dict format
        results_data = []
        for result in h1_results:
            results_data.append({
                "url": result.url,
                "h1_count": result.h1_count,
                "h1_texts": result.h1_texts,
                "issues": result.issues
            })
        
        return templates.TemplateResponse("h1-results.html", {
            "request": request,
            "user": user,
            "session": session,
            "session_id": session_id,
            "session_type": "h1",
            "results": results_data
        })
    elif session_type == "phone":
        # Get phone audit results
        phone_results = db.query(models.PhoneAuditResult).filter_by(session_id=session_id).all()
        
        # Convert results to dict format
        results_data = []
        for result in phone_results:
            results_data.append({
                "url": result.url,
                "phone_count": result.phone_count,
                "phone_numbers": result.phone_numbers,
                "formats_detected": result.formats_detected,
                "issues": result.issues
            })
        
        return templates.TemplateResponse("phone-results.html", {
            "request": request,
            "user": user,
            "session": session,
            "session_id": session_id,
            "session_type": "phone",
            "results": results_data
        })
    elif session_type == "unified":
        return RedirectResponse(f"/unified-results/{session_id}")
    elif session_type == "accessibility":
        return RedirectResponse(f"/accessibility-results/{session_id}")
    else:
        raise HTTPException(status_code=400, detail="Invalid session type")

@app.get("/h1-results/{session_id}")
async def get_h1_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """Get H1 audit results for a session - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Verify ownership
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get results
    results = db.query(models.H1AuditResult).filter_by(session_id=session_id).all()
    
    # Convert to list of dicts
    results_data = []
    for result in results:
        try:
            h1_texts = json.loads(result.h1_texts) if result.h1_texts else []
            issues = json.loads(result.issues) if result.issues else []
        except:
            h1_texts = []
            issues = []
            
        results_data.append({
            "url": result.url,
            "h1_count": result.h1_count,
            "h1_texts": h1_texts,
            "issues": issues,
            "created_at": result.created_at.isoformat() if result.created_at else None
        })
    
    return JSONResponse(results_data)

@app.get("/phone-results/{session_id}")
async def get_phone_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """Get phone audit results for a session - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Verify ownership
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get results
    results = db.query(models.PhoneAuditResult).filter_by(session_id=session_id).all()
    
    # Convert to list of dicts
    results_data = []
    for result in results:
        try:
            phone_numbers = json.loads(result.phone_numbers) if result.phone_numbers else []
            formats_detected = json.loads(result.formats_detected) if result.formats_detected else []
            issues = json.loads(result.issues) if result.issues else []
        except:
            phone_numbers = []
            formats_detected = []
            issues = []
            
        results_data.append({
            "url": result.url,
            "phone_count": result.phone_count,
            "phone_numbers": phone_numbers,
            "formats_detected": formats_detected,
            "issues": issues,
            "created_at": result.created_at.isoformat() if result.created_at else None
        })
    
    return JSONResponse(results_data)

@app.get("/check-files/{session_type}/{session_id}")
async def check_files(session_type: str, session_id: str, browser: str, url: str):
    """Check if files exist for a specific URL and browser"""
    try:
        unique = get_unique_filename(url)
        
        if session_type == "static":
            # Check for screenshots
            files_exist = []
            resolutions = ["1920x1080", "1366x768", "1280x720", "1024x768", "768x1024", "480x800"]
            
            for res in resolutions:
                file_path = f"screenshots/{session_id}/{browser}/{unique}__{res}.png"
                if os.path.exists(file_path):
                    files_exist.append(res)
            
            return {"files_exist": files_exist, "total_checked": len(resolutions)}
        elif session_type == "dynamic":
            # Check for videos
            files_exist = []
            resolutions = ["1920x1080", "1366x768", "1280x720", "1024x768", "768x1024", "480x800"]
            
            for res in resolutions:
                file_path = f"videos/{session_id}/{browser}/{unique}__{res}.mp4"
                if os.path.exists(file_path):
                    files_exist.append(res)
            
            return {"files_exist": files_exist, "total_checked": len(resolutions)}
        else:
            return {"files_exist": [], "total_checked": 0}
    except Exception as e:
        return {"error": str(e), "files_exist": [], "total_checked": 0}

# ========== STREAMING RESPONSE FOR VIDEOS ==========

@app.get("/videos/{session_id}/{browser}/{video_file}")
async def stream_video(session_id: str, browser: str, video_file: str, request: Request):
    """Stream video files for dynamic results"""
    video_path = f"videos/{session_id}/{browser}/{video_file}"
    
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video not found")
    
    file_size = os.path.getsize(video_path)
    range_header = request.headers.get("Range")
    
    if range_header:
        # Parse Range header
        start_str, end_str = range_header.replace("bytes=", "").split("-")
        start = int(start_str)
        end = int(end_str) if end_str else file_size - 1
        
        if start >= file_size:
            raise HTTPException(status_code=416, detail="Range not satisfiable")
        
        end = min(end, file_size - 1)
        length = end - start + 1
        
        with open(video_path, "rb") as video:
            video.seek(start)
            data = video.read(length)
        
        response = StreamingResponse(
            iter([data]),
            status_code=206,
            media_type="video/mp4",
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
                "Content-Disposition": f"inline; filename={video_file}"
            }
        )
        return response
    else:
        # Return full file
        file_like = open(video_path, mode="rb")
        return StreamingResponse(
            file_like,
            media_type="video/mp4",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
                "Content-Disposition": f"inline; filename={video_file}"
            }
        )

# ========== VISUAL REGRESSION FUNCTIONS ==========

async def compare_images_logic(base_url: str, compare_url: str, session_id: str, db: Session):
    session_folder = f"diffs/{session_id}"
    os.makedirs(session_folder, exist_ok=True)
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1280, "height": 800})
            page = await context.new_page()
            
            # Capture Base
            await page.goto(base_url, wait_until="networkidle", timeout=30000)
            base_path = f"{session_folder}/base.png"
            await page.screenshot(path=base_path, full_page=True)
            
            # Capture Compare
            await page.goto(compare_url, wait_until="networkidle", timeout=30000)
            compare_path = f"{session_folder}/compare.png"
            await page.screenshot(path=compare_path, full_page=True)
            
            await browser.close()
            
            # Compare logic
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(executor, process_image_diff, base_path, compare_path, session_folder, session_id, base_url, compare_url)

    except Exception as e:
        print(f"Visual Audit Error: {e}")
        # Update db in main thread if possible or pass db to executor? 
        # Here we just log. The executor function handles the db update? No, existing db session is not thread safe.
        # We need to handle DB updates here.
        # Since we closed browser, let's do the DB update logic here for error?
        pass

def process_image_diff(base_path, compare_path, session_folder, session_id, base_url, compare_url):
    # This runs in a thread
    import database
    from sqlalchemy.orm import Session
    
    # Create new db session for thread
    db = database.SessionLocal()
    
    try:
        img1 = Image.open(base_path).convert("RGB")
        img2 = Image.open(compare_path).convert("RGB")
        
        # Resize to match smallest dimensions to avoid errors
        width = min(img1.width, img2.width)
        height = min(img1.height, img2.height)
        
        img1 = img1.resize((width, height))
        img2 = img2.resize((width, height))
        
        diff_img = Image.new("RGB", (width, height))
        diff_pixels = diff_img.load()
        
        pixels1 = img1.load()
        pixels2 = img2.load()
        
        diff_count = 0
        total_pixels = width * height
        
        for y in range(height):
            for x in range(width):
                r1, g1, b1 = pixels1[x, y]
                r2, g2, b2 = pixels2[x, y]
                
                diff = abs(r1 - r2) + abs(g1 - g2) + abs(b1 - b2)
                if diff > 15: # Threshold
                    diff_pixels[x, y] = (255, 0, 0) # Highlight Red
                    diff_count += 1
                else:
                    # Fade out slightly
                    diff_pixels[x, y] = (int(r1*0.3), int(g1*0.3), int(b1*0.3))
        
        diff_path = f"{session_folder}/diff.png"
        diff_img.save(diff_path)
        
        diff_score = int((diff_count / total_pixels) * 100)
        
        # Save Result
        result = models.VisualAuditResult(
            session_id=session_id,
            base_url=base_url,
            compare_url=compare_url,
            diff_score=diff_score,
            base_image_path=base_path,
            compare_image_path=compare_path,
            diff_image_path=diff_path
        )
        db.add(result)
        
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "completed"
            session.completed = 1
            session.completed_at = datetime.utcnow()
            db.commit()
            
    except Exception as e:
        print(f"Diff processing error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            db.commit()
    finally:
        db.close()

# ========== ACCESSIBILITY AUDIT FUNCTIONS ==========

async def audit_accessibility_logic(urls: List[str], session_id: str, db: Session):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            
            for url in urls:
                try:
                    # Check if stopped
                    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session and session.status == "stopped":
                        break

                    context = await browser.new_context()
                    page = await context.new_page()
                    
                    await page.goto(url, wait_until="networkidle", timeout=60000)
                    
                    # Inject Axe-core
                    await page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.7.2/axe.min.js")
                    
                    # Run Axe
                    results = await page.evaluate("() => axe.run()")
                    
                    # Process Results
                    violations = results.get("violations", [])
                    score = 100 - (len(violations) * 5)
                    if score < 0: score = 0
                    
                    critical = 0
                    serious = 0
                    moderate = 0
                    minor = 0
                    
                    for v in violations:
                        impact = v.get("impact", "minor")
                        if impact == "critical": critical += 1
                        elif impact == "serious": serious += 1
                        elif impact == "moderate": moderate += 1
                        else: minor += 1
                    
                    audit_result = models.AccessibilityAuditResult(
                        session_id=session_id,
                        url=url,
                        score=score,
                        violations_count=len(violations),
                        critical_count=critical,
                        serious_count=serious,
                        moderate_count=moderate,
                        minor_count=minor,
                        report_json=json.dumps(violations)
                    )
                    db.add(audit_result)
                    
                    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    session.completed += 1
                    db.commit()
                    
                    await context.close()
                    
                except Exception as e:
                    print(f"Accessibility Error {url}: {e}")
                    # Log error result?
            
            await browser.close()
            
            session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
            if session:
                session.status = "completed"
                session.completed_at = datetime.utcnow()
                db.commit()

    except Exception as e:
        print(f"Accessibility Audit Fatal Error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            db.commit()


# ========== PERFORMANCE AUDIT FUNCTIONS ==========

async def audit_performance_logic(urls: List[str], session_id: str):
    # Create a new database session for this background task
    db = database.SessionLocal()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            
            for url in urls:
                try:
                    context = await browser.new_context()
                    page = await context.new_page()
                    
                    # Navigate and measure
                    response = await page.goto(url, wait_until="load", timeout=45000)
                    
                    # Get Timing Metrics via Navigation API
                    timings = await page.evaluate("() => JSON.stringify(window.performance.timing)")
                    timings = json.loads(timings)
                    
                    # Calculate key metrics
                    nav_start = timings['navigationStart']
                    ttfb = max(0, timings['responseStart'] - nav_start)
                    dom_load = max(0, timings['domContentLoadedEventEnd'] - nav_start)
                    page_load = max(0, timings['loadEventEnd'] - nav_start)
                    
                    # First Contentful Paint (approximate via paint timing api if available)
                    fcp = 0
                    try:
                        fcp_raw = await page.evaluate("""() => {
                            const paint = performance.getEntriesByType('paint').find(e => e.name === 'first-contentful-paint');
                            return paint ? paint.startTime : 0;
                        }""")
                        fcp = int(fcp_raw)
                    except:
                        pass
                    
                    # Resource counting
                    resource_count = await page.evaluate("performance.getEntriesByType('resource').length")
                    
                    # Simple scoring logic
                    score = 100
                    if page_load > 3000: score -= 10
                    if page_load > 5000: score -= 20
                    if ttfb > 500: score -= 10
                    if score < 0: score = 0
                    
                    result = models.PerformanceAuditResult(
                        session_id=session_id,
                        url=url,
                        ttfb=ttfb,
                        fcp=fcp,
                        dom_load=dom_load,
                        page_load=page_load,
                        resource_count=resource_count,
                        score=score
                    )
                    db.add(result)
                    
                    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    session.completed += 1
                    db.commit()
                    
                    await context.close()
                    
                except Exception as e:
                    print(f"Perf Error {url}: {e}")
            
            await browser.close()
            
            session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
            if session:
                session.status = "completed"
                session.completed_at = datetime.utcnow()
                db.commit()

    except Exception as e:
        print(f"Performance Audit Fatal Error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            db.commit()
    finally:
        db.close()


# ========== NEW ROUTES ==========

@app.get("/platform/dashboard", response_class=HTMLResponse)
async def platform_dashboard(request: Request, user: models.User = Depends(require_auth), db: Session = Depends(auth.get_db)):
    # Stats
    total_sessions = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id).count()
    recent_sessions = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id).order_by(models.AuditSession.created_at.desc()).limit(5).all()
    
    # Calculate simple pass rate (mock)
    completed = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id, models.AuditSession.status == "completed").count()
    success_rate = int((completed / total_sessions * 100)) if total_sessions > 0 else 0
    
    # Mock active jobs for now
    active_jobs = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id, models.AuditSession.status == "running").count()

    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "user": user, 
        "total_sessions": total_sessions,
        "success_rate": success_rate,
        "recent_sessions": recent_sessions,
        "active_jobs": active_jobs
    })

@app.get("/platform/device-lab", response_class=HTMLResponse)
async def device_lab_view(request: Request, user: models.User = Depends(require_auth)):
    return templates.TemplateResponse("device_lab.html", {"request": request, "user": user})

@app.get("/platform/visual", response_class=HTMLResponse)
async def visual_test_view(request: Request, user: models.User = Depends(require_auth)):
    return templates.TemplateResponse("visual_regression.html", {"request": request, "user": user})

@app.get("/platform/performance", response_class=HTMLResponse)
async def performance_test_view(request: Request, user: models.User = Depends(require_auth), db: Session = Depends(auth.get_db)):
    # Fetch recent performance audit results for this user
    recent_results = db.query(models.PerformanceAuditResult).join(
        models.AuditSession, models.PerformanceAuditResult.session_id == models.AuditSession.session_id
    ).filter(
        models.AuditSession.user_id == user.id
    ).order_by(models.PerformanceAuditResult.id.desc()).limit(10).all()
    
    return templates.TemplateResponse("performance_audit.html", {
        "request": request, 
        "user": user,
        "recent_results": recent_results
    })

@app.post("/api/visual-test")
async def trigger_visual_test(
    background_tasks: BackgroundTasks, 
    base_url: str = Form(...), 
    compare_url: str = Form(...), 
    user: models.User = Depends(require_auth), 
    db: Session = Depends(auth.get_db)
):
    session_id = f"vis_{uuid.uuid4().hex[:8]}"
    
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        session_type="visual",
        name=f"Visual: {get_unique_filename(base_url)}",
        urls=json.dumps([base_url, compare_url]),
        browsers=json.dumps(["Chrome"]),
        resolutions=json.dumps(["1280x800"]),
        total_expected=1
    )
    db.add(new_session)
    db.commit()
    
    background_tasks.add_task(compare_images_logic, base_url, compare_url, session_id, db)
    
    return RedirectResponse(url="/platform/visual?status=started", status_code=303)

@app.post("/api/performance-test")
async def trigger_performance_test(
    background_tasks: BackgroundTasks,
    urls: str = Form(...),
    user: models.User = Depends(require_auth),
    db: Session = Depends(auth.get_db)
):
    url_list = [u.strip() for u in urls.splitlines() if u.strip()]
    session_id = f"perf_{uuid.uuid4().hex[:8]}"
    
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        session_type="performance",
        name=f"Perf: {len(url_list)} URLs",
        urls=json.dumps(url_list),
        browsers=json.dumps(["Chrome"]),
        resolutions=json.dumps(["Default"]),
        total_expected=len(url_list)
    )
    db.add(new_session)
    db.commit()
    
    background_tasks.add_task(audit_performance_logic, url_list, session_id)
    
    return RedirectResponse(url="/platform/performance?status=started", status_code=303)

@app.get("/api/results/{session_id}")
async def get_any_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """Generic results endpoint"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401)
        
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        raise HTTPException(status_code=404)
        
    if session.session_type == "visual":
         results = db.query(models.VisualAuditResult).filter_by(session_id=session_id).all()
         return [{"score": r.diff_score, "diff_img": r.diff_image_path} for r in results]
    elif session.session_type == "performance":
         results = db.query(models.PerformanceAuditResult).filter_by(session_id=session_id).all()
         return [{
             "url": r.url,
             "ttfb": r.ttfb,
             "fcp": r.fcp,
             "score": r.score
         } for r in results]
    return []

@app.get("/platform/accessibility", response_class=HTMLResponse)
async def accessibility_test_view(request: Request, user: models.User = Depends(require_auth)):
    return templates.TemplateResponse("accessibility-audit.html", {"request": request, "user": user})

@app.post("/api/accessibility-test")
async def trigger_accessibility_test(
    background_tasks: BackgroundTasks,
    urls: str = Form(...),
    user: models.User = Depends(require_auth),
    db: Session = Depends(auth.get_db)
):
    url_list = [u.strip() for u in urls.splitlines() if u.strip()]
    session_id = f"a11y_{uuid.uuid4().hex[:8]}"
    
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        session_type="accessibility",
        name=f"A11y: {len(url_list)} URLs",
        urls=json.dumps(url_list),
        browsers=json.dumps(["Chrome"]),
        resolutions=json.dumps(["Default"]),
        total_expected=len(url_list)
    )
    db.add(new_session)
    db.commit()
    
    background_tasks.add_task(audit_accessibility_logic, url_list, session_id, db)
    
    return RedirectResponse(url="/platform/accessibility?status=started", status_code=303)

@app.get("/accessibility-results/{session_id}")
async def get_accessibility_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
        
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404)
        
    results = db.query(models.AccessibilityAuditResult).filter_by(session_id=session_id).all()
    
    return templates.TemplateResponse("accessibility-results.html", {
        "request": request, 
        "user": user,
        "session": session,
        "results": results
    })


# ========== PROXY ENDPOINT ==========

@app.get("/api/proxy")
async def proxy_url(url: str):
    """Proxy endpoint to bypass X-Frame-Options"""
    if not url.startswith("http"):
        url = "https://" + url
        
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(url, timeout=10.0)
            
            # Filter headers that block iframes or cause encoding issues
            excluded_headers = [
                'x-frame-options', 
                'content-security-policy', 
                'frame-options',
                'content-encoding',
                'transfer-encoding',
                'content-length' 
            ]
            headers = {
                k: v for k, v in resp.headers.items() 
                if k.lower() not in excluded_headers
            }
            
            # Rewrite relative links (simple attempt) - robust rewriting is complex, 
            # this is a basic "Device Lab" simulation proxy.
            content = resp.content
            
            return Response(content=content, status_code=resp.status_code, headers=headers)
    except Exception as e:
        return Response(content=f"Proxy Error: {str(e)}", status_code=502)


# ========== UNIFIED AUDIT FUNCTIONS ==========

async def audit_unified_logic(urls: List[str], session_id: str, user_id: int):
    # Create new session for background task
    db = database.SessionLocal()
    try:
        # Launch concurrently
        tasks = []
        
        # 1. Performance (Manages its own session, no DB arg needed)
        tasks.append(audit_performance_logic(urls, session_id))
        
        # 2. Accessibility (Needs DB)
        tasks.append(audit_accessibility_logic(urls, session_id, db))
        
        # 3. H1 / SEO (Needs DB)
        tasks.append(audit_h1_tags(urls, session_id, user_id, db))
        
        # 4. Phone / Content (Needs DB)
        tasks.append(audit_phone_numbers(urls, ["US", "UK", "IN"], ["validate"], session_id, user_id, db))
        
        await asyncio.gather(*tasks)
        
        # Aggregate Results
        for url in urls:
            try:
                # Default Scores
                perf_score = 0
                a11y_score = 0
                seo_score = 0
                content_score = 0
                
                # Fetch sub-results
                perf_res = db.query(models.PerformanceAuditResult).filter_by(session_id=session_id, url=url).first()
                if perf_res: perf_score = perf_res.score
                
                a11y_res = db.query(models.AccessibilityAuditResult).filter_by(session_id=session_id, url=url).first()
                if a11y_res: a11y_score = a11y_res.score
                
                # Calculate basic SEO score from H1
                h1_res = db.query(models.H1AuditResult).filter_by(session_id=session_id, url=url).first()
                if h1_res:
                     issues = json.loads(h1_res.issues)
                     seo_score = 100 - (len(issues) * 10)
                     if seo_score < 0: seo_score = 0
                
                # Calculate basic Content score from Phone
                phone_res = db.query(models.PhoneAuditResult).filter_by(session_id=session_id, url=url).first()
                if phone_res:
                     content_score = 100 # Optimistic default if found
                     if phone_res.phone_count == 0: content_score = 50 # Maybe okay, but low
                
                # Overall
                overall = int((perf_score + a11y_score + seo_score + content_score) / 4)
                
                unified_res = models.UnifiedAuditResult(
                    session_id=session_id,
                    url=url,
                    performance_score=perf_score,
                    accessibility_score=a11y_score,
                    seo_score=seo_score,
                    content_score=content_score,
                    overall_score=overall
                )
                db.add(unified_res)
                
            except Exception as e:
                print(f"Aggregation Error {url}: {e}")
        
        db.commit()
        
        # Mark Session Complete
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "completed"
            session.completed = 100
            session.completed_at = datetime.utcnow()
            db.commit()
            
    except Exception as e:
        print(f"Unified Audit Error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            db.commit()
    finally:
        db.close()

@app.get("/platform/unified", response_class=HTMLResponse)
async def unified_audit_view(request: Request, user: models.User = Depends(require_auth)):
    return templates.TemplateResponse("unified-audit.html", {"request": request, "user": user})

@app.post("/api/unified-test")
async def trigger_unified_test(
    background_tasks: BackgroundTasks,
    urls: str = Form(...),
    user: models.User = Depends(require_auth),
    db: Session = Depends(auth.get_db)
):
    url_list = [u.strip() for u in urls.splitlines() if u.strip()]
    if not url_list:
        raise HTTPException(status_code=400, detail="No URLs provided")
        
    session_id = f"uni_{uuid.uuid4().hex[:8]}"
    
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        session_type="unified",
        name=f"Unified: {len(url_list)} URLs",
        urls=json.dumps(url_list),
        browsers=json.dumps(["Chrome"]),
        resolutions=json.dumps(["Default"]),
        total_expected=len(url_list) * 4 
    )
    db.add(new_session)
    db.commit()
    
    background_tasks.add_task(audit_unified_logic, url_list, session_id, user.id)
    
    return RedirectResponse(url="/platform/unified?status=started", status_code=303)

@app.get("/unified-results/{session_id}")
async def get_unified_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
        
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404)
        
    results = db.query(models.UnifiedAuditResult).filter_by(session_id=session_id).all()
    
    return templates.TemplateResponse("unified-results.html", {
        "request": request, 
        "user": user,
        "session": session,
        "results": results
    })

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)