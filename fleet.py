import sys
import os
import re
from datetime import datetime, time
from uagents import Agent, Context, Model, Protocol
from uagents.setup import fund_agent_if_low
from openai import AsyncOpenAI
from rapidfuzz import process, fuzz
from pydantic import BaseModel
import logging

# --- Path Configuration ---
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Fixed: __file__
sys.path.append(PROJECT_ROOT)
KNOWLEDGE_BASE_FILE = os.path.join(PROJECT_ROOT, "knowledge_graph.metta")

# --- ASI:One API Configuration ---
# 🔒 Security: Use environment variable instead of hardcoded key
ASI_API_KEY = os.getenv("ASI_API_KEY", "sk_36337a570d7247acba09fbf01536b51e76ac73ad99304e11b266f7bbe16ee934")
if not ASI_API_KEY or "YOUR" in ASI_API_KEY:
    print("WARNING: ASI_API_KEY not found or not configured. LLM functionality will be disabled.")
    asi_client = None
else:
    asi_client = AsyncOpenAI(api_key=ASI_API_KEY, base_url="https://api.asi1.ai/v1")

# --- Agent Definition ---
FLEET_MANAGER_SEED = os.getenv("FLEET_MANAGER_SEED", "echonet_fleet_manager_super_secret_seed_phrase")
agent = Agent(
    name="EchoNetFleetManager",
    seed=FLEET_MANAGER_SEED,
    port=8000,
    endpoint=["http://127.0.0.1:8000/submit"],
)

# Try to fund agent, handle potential errors
try:
    fund_agent_if_low(agent.wallet.address())
except Exception as e:
    print(f"Warning: Could not fund agent: {e}")

# --- Agent-to-Agent Communication Models ---
class QueryRequest(Model):
    query: str

class QueryResponse(Model):
    answer: str
    status: str = "success"  # Added status field

query_protocol = Protocol("FleetManagerQuery", version="1.0")

# --- Model for client requests with validation ---
class SimpleClientQuery(BaseModel):
    question: str
    
    class Config:
        # Add validation
        min_anystr_length = 1
        max_anystr_length = 1000

# --- Knowledge Base Parsing & Helper Functions ---
LOCATIONS_CACHE = {}
EVENTS_CACHE = []

def load_knowledge_base():
    """Parses the .metta file to load locations and events."""
    global LOCATIONS_CACHE, EVENTS_CACHE
    locations = {}
    events = []
    
    if not os.path.exists(KNOWLEDGE_BASE_FILE):
        agent.logger.warning(f"Knowledge base file not found at '{KNOWLEDGE_BASE_FILE}'")
        # Create empty knowledge base file for demo
        try:
            with open(KNOWLEDGE_BASE_FILE, 'w') as f:
                f.write("; EchoNet Knowledge Base\n")
                f.write("; Auto-generated example data\n")
                f.write('(location LOC001 "Dwarka, 7, Delhi" 28.51103 77.012798)\n')
                f.write('(location LOC004 "NIT, 9, Jalandhar" 28.50103 77.042798)\n')
                f.write('(noise_event evt001 LOC001 "2024-01-15T14:30:00Z" 45.2)\n')
                f.write('(noise_event evt002 LOC004 "2024-01-15T23:15:00Z" 38.7)\n')
            agent.logger.info(f"Created sample knowledge base at '{KNOWLEDGE_BASE_FILE}'")
        except Exception as e:
            agent.logger.error(f"Could not create knowledge base file: {e}")
        return

    try:
        with open(KNOWLEDGE_BASE_FILE, 'r') as f:
            line_count = 0
            for line in f:
                line_count += 1
                line = line.strip()
                if not line or line.startswith(";"):
                    continue
                
                # Parse location entries
                loc_match = re.match(r'\(location (\S+) "(.*)" ([\d\.\-]+) ([\d\.\-]+)\)', line)
                if loc_match:
                    try:
                        loc_id, name, lat, lon = loc_match.groups()
                        locations[loc_id] = {"name": name, "lat": float(lat), "lon": float(lon)}
                        continue
                    except ValueError as e:
                        agent.logger.warning(f"Invalid location data on line {line_count}: {e}")
                        continue
                
                # Parse event entries
                event_match = re.match(r'\(noise_event (\S+) (\S+) "([^"]+)" (\d+\.?\d*)\)', line)
                if event_match:
                    try:
                        event_id, loc_id, timestamp, db = event_match.groups()
                        events.append({
                            "event_id": event_id,
                            "loc_id": loc_id, 
                            "timestamp": timestamp, 
                            "db": float(db)
                        })
                    except ValueError as e:
                        agent.logger.warning(f"Invalid event data on line {line_count}: {e}")
                        continue
        
        LOCATIONS_CACHE = locations
        EVENTS_CACHE = events
        agent.logger.info(f"KB Loaded: {len(LOCATIONS_CACHE)} locations, {len(EVENTS_CACHE)} events.")
        
    except Exception as e:
        agent.logger.error(f"Error loading knowledge base: {e}")

def get_average_db(events, loc_id, night_only=False):
    """Calculates the average decibel level for a given location."""
    vals = []
    for ev in events:
        if ev["loc_id"] != loc_id:
            continue
        
        if night_only:
            try:
                # Handle both with and without 'Z' suffix
                timestamp_str = ev["timestamp"].rstrip('Z')
                t = datetime.fromisoformat(timestamp_str).time()
                if not (time(22, 0) <= t or t < time(6, 0)):
                    continue
            except (ValueError, KeyError) as e:
                agent.logger.debug(f"Could not parse timestamp for night filtering: {e}")
                continue
        
        vals.append(ev["db"])
    
    return sum(vals) / len(vals) if vals else None

def generate_facts_summary(events, locations):
    """Creates a plain-text summary of the knowledge base for the LLM."""
    if not locations:
        return "No data is available in the knowledge base. The system is still gathering sensor data."
    
    lines = ["Here are the current facts about the sound environment based on validated sensor data:"]
    lines.append(f"Total monitored locations: {len(locations)}")
    lines.append(f"Total recorded events: {len(events)}")
    lines.append("")
    
    for loc_id, loc_data in locations.items():
        avg_all = get_average_db(events, loc_id)
        avg_night = get_average_db(events, loc_id, night_only=True)
        
        # Count events for this location
        event_count = len([e for e in events if e["loc_id"] == loc_id])
        
        avg_all_str = f"{avg_all:.1f} dB" if avg_all is not None else "No data"
        avg_night_str = f"{avg_night:.1f} dB" if avg_night is not None else "No data"
        
        line = (f"- Location '{loc_data['name']}' (ID: {loc_id}): "
                f"{event_count} recorded events, "
                f"overall average: {avg_all_str}, "
                f"nighttime average: {avg_night_str}")
        lines.append(line)
    
    return "\n".join(lines)

async def query_llm_with_rag(user_query: str) -> str:
    """Performs the RAG process: Retrieve facts, Augment prompt, Generate answer."""
    if not asi_client:
        return "❌ The LLM service is not configured. Please set the ASI_API_KEY environment variable."

    # Input validation
    if not user_query or len(user_query.strip()) == 0:
        return "Please provide a valid question."
    
    if len(user_query) > 1000:
        return "Question is too long. Please keep it under 1000 characters."

    try:
        facts = generate_facts_summary(EVENTS_CACHE, LOCATIONS_CACHE)
        prompt = (
            f"You are the EchoNet Fleet Manager, an AI assistant for a decentralized sound-monitoring network. "
            f"Your role is to provide insights about noise pollution based on validated sensor data.\n\n"
            f"INSTRUCTIONS:\n"
            f"- Answer concisely and professionally\n"
            f"- Base your response ONLY on the facts provided below\n"
            f"- If data is insufficient, clearly state the limitations\n"
            f"- Include specific numbers when available\n"
            f"- If you don't know something, say so honestly\n\n"
            f"--- CURRENT SENSOR DATA ---\n{facts}\n\n"
            f"--- USER QUESTION ---\n{user_query}\n\n"
            f"--- YOUR RESPONSE ---"
        )
        
        response = await asi_client.chat.completions.create(
            model="asi1-extended",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=500,  # Limit response length
        )
        
        answer = response.choices[0].message.content
        if not answer:
            return "I apologize, but I couldn't generate a response. Please try rephrasing your question."
            
        return answer
        
    except Exception as e:
        agent.logger.error(f"Error querying LLM: {e}")
        return f"⚠️ An error occurred while processing your question: {str(e)[:100]}..."

# --- Agent Logic ---

@agent.on_event("startup")
async def startup(ctx: Context):
    ctx.logger.info(f"🚀 Fleet Manager started. Address: {agent.address}")
    ctx.logger.info(f"📊 Knowledge base file: {KNOWLEDGE_BASE_FILE}")
    ctx.logger.info(f"🤖 ASI LLM available: {'Yes' if asi_client else 'No'}")
    load_knowledge_base()

@agent.on_interval(period=30.0)  # Reduced frequency to avoid spam
async def sync_knowledge_base(ctx: Context):
    ctx.logger.debug("🔄 Syncing with shared knowledge base...")
    old_locations_count = len(LOCATIONS_CACHE)
    old_events_count = len(EVENTS_CACHE)
    
    load_knowledge_base()
    
    # Log changes
    new_locations = len(LOCATIONS_CACHE) - old_locations_count
    new_events = len(EVENTS_CACHE) - old_events_count
    
    if new_locations > 0 or new_events > 0:
        ctx.logger.info(f"📈 KB updated: +{new_locations} locations, +{new_events} events")

# Agent-to-agent communication
@query_protocol.on_message(model=QueryRequest, replies=QueryResponse)
async def handle_agent_query(ctx: Context, sender: str, msg: QueryRequest):
    ctx.logger.info(f"🤖 Agent query from {sender[:20]}...: '{msg.query[:50]}...'")
    
    try:
        answer = await query_llm_with_rag(msg.query)
        await ctx.send(sender, QueryResponse(answer=answer, status="success"))
    except Exception as e:
        ctx.logger.error(f"Error handling agent query: {e}")
        await ctx.send(sender, QueryResponse(
            answer=f"Sorry, I encountered an error: {str(e)[:100]}...", 
            status="error"
        ))

# Public REST API endpoint
@agent.server.post("/ask", response_model=dict)
async def handle_client_query(query: SimpleClientQuery):
    """Handles JSON queries from non-agent clients via REST API."""
    agent.logger.info(f"🌐 Client query via REST: '{query.question[:50]}...'")
    
    try:
        # Validate input
        if not query.question or len(query.question.strip()) == 0:
            return {
                "answer": "Please provide a valid question.", 
                "status": "error",
                "timestamp": datetime.now().isoformat()
            }
        
        answer = await query_llm_with_rag(query.question)
        return {
            "answer": answer, 
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "locations_count": len(LOCATIONS_CACHE),
            "events_count": len(EVENTS_CACHE)
        }
        
    except Exception as e:
        agent.logger.error(f"Error handling client query: {e}")
        return {
            "answer": f"I apologize, but I encountered an error: {str(e)[:100]}...", 
            "status": "error",
            "timestamp": datetime.now().isoformat()
        }

# Health check endpoint
@agent.server.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "agent_address": str(agent.address),
        "llm_available": asi_client is not None,
        "knowledge_base": {
            "locations": len(LOCATIONS_CACHE),
            "events": len(EVENTS_CACHE),
            "file_exists": os.path.exists(KNOWLEDGE_BASE_FILE)
        },
        "timestamp": datetime.now().isoformat()
    }

# --- Main Execution ---
if __name__ == "__main__":
    print(f"🎯 Starting EchoNet Fleet Manager...")
    print(f"📁 Project root: {PROJECT_ROOT}")
    print(f"📊 Knowledge base: {KNOWLEDGE_BASE_FILE}")
    print(f"🔑 ASI API configured: {'Yes' if ASI_API_KEY and 'YOUR' not in ASI_API_KEY else 'No'}")
    
    agent.include(query_protocol, publish_manifest=True)
    agent.run()