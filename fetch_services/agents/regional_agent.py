import sys
import os
# --- Path Configuration ---
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(PROJECT_ROOT)

import asyncio
import hashlib
import json
from datetime import datetime, timezone, timedelta
import math
import random
import time
import requests
import numpy as np
import aiohttp

from uagents import Agent, Context, Protocol, Model
from uagents.crypto import Identity
from cosmpy.crypto.keypairs import PublicKey, PrivateKey
from mnemonic import Mnemonic

from fetch_services.agents.schemas import SensorData, ValidationRequest, ValidationResponse, FactCandidate, ValidatedSensorData , EnrichedData
from fetch_services.agents.ml_model import run_inference
from fetch_services.ipfs_service import IPFSService
from fetch_services.consensus.consensus_logic import SmartConsensus
# Import the Agentverse key, as workers now need it to create their mailboxes
from config.settings import AGENTVERSE_API_KEY

# The Notary Agent's address will be loaded dynamically from the registry
NOTARY_AGENT_ADDRESS = None
# The base URL for the central Flask server
API_BASE_URL = "https://fetch-dev.onrender.com"

def read_registry():
    """Fetches the sensor registry from the central API server."""
    try:
        response = requests.get(f"{API_BASE_URL}/registry", timeout=10)
        print(response)
        response.raise_for_status()  # Raise an exception for bad status codes
        print("Successfully fetched registry from API.")
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"CRITICAL: Could not fetch registry from API: {e}. Returning empty registry.")
        return {}

# --- Agent & Peer Configuration ---
if len(sys.argv) < 2:
    print(f"Usage: python {sys.argv[0]} <mac_address>")
    sys.exit(1)

MAC_ADDRESS = sys.argv[1]
ALL_CONFIGS = read_registry()
CONFIG = ALL_CONFIGS[MAC_ADDRESS]
AGENT_NAME = CONFIG['agent_name']

# --- Agent Setup (with Mailbox) ---
seed_bytes = Mnemonic("english").to_seed(CONFIG["agent_seed"])
private_key_bytes = seed_bytes[:32]
private_key = PrivateKey(private_key_bytes)
public_key = private_key.public_key

# FIX: The worker agent is now a pure mailbox agent, just like the Fleet Manager.
# It no longer uses a local port or endpoint.
agent = Agent(
    name=AGENT_NAME, 
    seed=CONFIG["agent_seed"],
    mailbox=f"{AGENTVERSE_API_KEY}@agentverse.ai",
)

# --- State & Helpers ---
# ... (all other helpers and state variables remain the same as the last working version) ...

# --- Protocols & Message Handlers ---
# ... (all message handlers remain the same, as ctx.send() automatically uses the mailbox) ...

# --- Main Execution ---



# --- State & Helpers ---
# ... (all helper functions and state variables are the same as the last working version) ...
LOCAL_SENSOR_STATE = {}
SENSOR_FAILURE_COUNTS = {} 
FAILURE_THRESHOLD = 5 
PENDING_LOCK = asyncio.Lock()
pending_events = {}
VALIDATION_TIMEOUT = timedelta(seconds=15)
GRID_SIZE = 0.1
ipfs_service = IPFSService()
smart_consensus = SmartConsensus()
QUORUM_RATIO = 0.45 

def export_public_key_hex(pubkey: PublicKey) -> str:
    """Safely exports a cosmpy PublicKey to a hex string."""
    return pubkey._verifying_key.to_string().hex()

def get_digest(data: dict) -> bytes:
    """Creates a consistent, sorted hash for a dictionary."""
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).digest()

# NEW: Upgraded cleanup function with on-chain slashing request
def cleanup_sensor_and_agent(mac_address: str):
    """
    Removes a faulty sensor by first requesting an on-chain stake slash,
    then removing it from the off-chain configuration.
    """
    print(f"CRITICAL: Sensor with MAC {mac_address} has exceeded failure threshold.")
    
    # 1. Request the on-chain stake slash from the secure API server.
    print(f"--> Requesting on-chain stake slash from the API server...")
    try:
        # NOTE: This is a synchronous call for simplicity in this function.
        response = requests.post(
            "https://fetch-dev.onrender.com/request-slash",
            json={"mac_address": mac_address},
            timeout=20
        )
        response.raise_for_status()
        api_ack = response.json()
        print(f"--> API Acknowledged Slash Request: {api_ack.get('message')} (Tx: {api_ack.get('tx_hash')})")

        # 2. After the slash, the agent should notify the server to remove the sensor.
        # This part is simplified as the agent doesn't directly modify the registry anymore.
        # A dedicated API endpoint on the server would be needed to handle removal securely.
        print(f"--> Sensor {mac_address} should be removed from the registry by an administrator or via a secure API call.")

    except requests.exceptions.RequestException as e:
        print(f"--> CRITICAL: Failed to send slash request to API: {e}")


def get_local_peer_group(event_location: dict) -> set:
    """Calculates the local peer group based on the shared JSON config."""
    local_peers = set()
    all_configs = read_registry() 
    event_grid_id = (math.floor(event_location["latitude"] / GRID_SIZE), math.floor(event_location["longitude"] / GRID_SIZE))
    for mac, cfg in all_configs.items():
        if not mac.startswith('_'): 
            peer_grid_id = (math.floor(cfg["latitude"] / GRID_SIZE), math.floor(cfg["longitude"] / GRID_SIZE))
            if peer_grid_id == event_grid_id:
                peer_address = str(Identity.from_seed(cfg["agent_seed"], 0).address)
                local_peers.add(peer_address)
    return local_peers



async def final_actions_after_consensus(ctx: Context, event_info: dict, location: dict):
    """
    Performs all three data forwarding actions after a successful consensus.
    1. Uploads raw data to a local API (instead of IPFS).
    2. Forwards a fact to the Notary Agent.
    3. Forwards an enriched packet to the external API.
    """
    global NOTARY_AGENT_ADDRESS
    raw_data = event_info["raw_data"]
    print(raw_data)

    # # 1. Send the original raw data to a locally running API instead of IPFS
    # ipfs_link = " "
    # local_api_url = "http://82.177.167.151:3001/api/sensor"  # <-- replace with your actual local API endpoint
    # try:
    #     async with aiohttp.ClientSession() as session:
    #         async with session.post(local_api_url, json=raw_data, timeout=10) as resp:
    #             try:
    #                 resp_json = await resp.json()
    #             except Exception:
    #                 resp_text = await resp.text()
    #                 resp_json = {"status_text": resp_text}
    #             ipfs_link = resp_json.get("ipfs_link", "")
    #             ctx.logger.info(f"Consensus reached. Raw data sent to local API: {resp_json}")
    # except asyncio.CancelledError:
    #     raise
    # except Exception as e:
    #     ctx.logger.error(f"Failed to send raw data to local API at {local_api_url}: {e}")
    # 1. Send the original raw data to a locally running API instead of IPFS
    ipfs_link = " "
    local_api_url = "http://82.177.167.151:3001/api/sensor"  # <-- replace with your actual local API endpoint
    
    # Transform raw_data to use deviceId instead of device_id
    transformed_data = {
        "deviceId": raw_data['device_id'],  # Change device_id to deviceId
        "timestamp": raw_data['timestamp'],
        "decibel": raw_data['decibel']
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(local_api_url, json=transformed_data, timeout=10) as resp:
                try:
                    resp_json = await resp.json()
                except Exception:
                    resp_text = await resp.text()
                    resp_json = {"status_text": resp_text}
                ipfs_link = resp_json.get("ipfs_link", "")
                ctx.logger.info(f"Consensus reached. Raw data sent to local API: {resp_json}")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        ctx.logger.error(f"Failed to send raw data to local API at {local_api_url}: {e}")

    # 2. Forward Fact to Notary Agent
    if NOTARY_AGENT_ADDRESS is None:
        registry = read_registry()
        NOTARY_AGENT_ADDRESS = registry.get("_network_services", {}).get("notary_agent_address")
    
    if NOTARY_AGENT_ADDRESS:
        # --- FIX: Use the correct 'location' parameter that was passed to the function ---
        
        # a. Create the location dictionary with "lat" and "lon" keys
        formatted_location = {
            "lat": location["latitude"],
            "lon": location["longitude"]
        }

        # b. Create the inner ValidatedSensorData object with the correct field names
        validated_data = ValidatedSensorData(
            mac_address=raw_data['device_id'],
            timestamp=datetime.fromisoformat(raw_data['timestamp']).timestamp(),
            sound_level_db=raw_data['decibel'],
            location=formatted_location
        )
        
        # c. Wrap it in the FactCandidate model
        fact = FactCandidate(validated_event=validated_data)
        
        # d. Send the final, correctly formatted message to the Notary
        await ctx.send(NOTARY_AGENT_ADDRESS, fact)
        ctx.logger.info(f"Fact candidate sent to Notary Agent.")
    else:
        ctx.logger.error("Could not find Notary Agent address in registry.")

    # 3. Forward Enriched Packet to External API (async version, using EnrichedData schema)
   # 3. Forward Enriched Packet to External API (async version, using EnrichedData schema)
    validator_pub_keys = [res.public_key for res in event_info["responses"] if res.validated]

        # Remap to external API schema
    payload = {
        "mac_address": raw_data['device_id'],
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "decibel_level": raw_data['decibel'],
        "event_type": event_info["predicted_class"],
        "metadata": {
            "source": "sensor_network",       # static for now
            "location_name": "Unknown"        # ⚠ can add reverse geocoding later
        }
    }


    url = "http://82.177.167.151:5001/ingest"  # <-- update if needed
    ctx.logger.info("🚀 SENDING ENRICHED PACKET TO EXTERNAL API 🚀")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as resp:
                try:
                    resp_json = await resp.json()
                except Exception:
                    resp_text = await resp.text()
                    resp_json = {"status_text": resp_text}
                ctx.logger.info(f"API Response status={resp.status}, body={resp_json}")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        ctx.logger.error(f"Failed to send enriched packet to {url}: {e}")

# --- Protocols & Message Handlers ---
validation_protocol = Protocol("WorkerAgentValidation")

@validation_protocol.on_message(model=SensorData, replies=set())
@validation_protocol.on_message(model=SensorData, replies=set())
async def handle_sensor_data(ctx: Context, sender: str, msg: SensorData):
    """Handles this agent's own sensor data and orchestrates consensus."""

    global LOCAL_SENSOR_STATE
    LOCAL_SENSOR_STATE = msg.dict()
    
    sensor_mac = msg.device_id
    all_configs = read_registry()
    print(all_configs)
    print(sensor_mac)
    if sensor_mac not in all_configs:
        return
        
    registered_location = {
        "latitude": all_configs[sensor_mac]["latitude"],
        "longitude": all_configs[sensor_mac]["longitude"]
    }
    
    # AI model is run, but IPFS/upload is deferred until after consensus.
    predicted_class, confidence = run_inference(np.array([]))
    
    event_id = hashlib.sha256(f"{msg.device_id}-{msg.timestamp}".encode()).hexdigest()
    event_local_group = get_local_peer_group(registered_location)

    print(event_local_group)

    async with PENDING_LOCK:
        pending_events[event_id] = {
            "raw_data": msg.dict(),
            "responses": [],
            "timestamp": datetime.now(timezone.utc),
            "predicted_class": predicted_class,
            "confidence": confidence
        }

    # --- SINGLE-AGENT AUTO-CONSENSUS ---
    if len(event_local_group) <= 1:  # Only this agent
        ctx.logger.info(f"No peers available. Auto-accepting event {event_id}.")
        await final_actions_after_consensus(ctx, pending_events[event_id], registered_location)
        async with PENDING_LOCK:
            del pending_events[event_id]
        return  # Skip sending ValidationRequest

    # --- MULTI-AGENT VALIDATION FLOW ---
    request_data = {
        "event_id": event_id,
        "location": registered_location,
        "sound_class": predicted_class,
        "decibel": msg.decibel
    }

    print("Request Data :" ,request_data)
    digest = get_digest(request_data)
    signature_bytes = private_key.sign(digest)
    print("Digest: ",digest)
    print("signature : ",signature_bytes)
    validation_request = ValidationRequest(
        **request_data,
        public_key=export_public_key_hex(public_key),
        signature=signature_bytes.hex(),
    )
    print(validation_protocol)
    # Send ValidationRequest to all peers
    for peer_address in event_local_group:
        if peer_address != str(agent.address):
            await ctx.send(peer_address, validation_request)


@validation_protocol.on_message(model=ValidationRequest, replies=set())
async def handle_validation_request(ctx: Context, sender: str, msg: ValidationRequest):
    """Handles validation requests from peers using REAL local sensor data."""
    is_plausible = False
    if not LOCAL_SENSOR_STATE:
        ctx.logger.warning("Validation request received, but no local sensor data available.")
    else:
        is_plausible = smart_consensus.validate_event(
            request_data=msg.dict(),
            peer_sensor_data=LOCAL_SENSOR_STATE,
            peer_agent_config=CONFIG
        )
    
    response_data = {"event_id": msg.event_id, "validated": is_plausible}
    digest = get_digest(response_data)
    signature_bytes = private_key.sign(digest)
    validation_response = ValidationResponse(
        **response_data,
        public_key=export_public_key_hex(public_key),
        signature=signature_bytes.hex(),
    )
    await ctx.send(sender, validation_response)

@validation_protocol.on_message(model=ValidationResponse, replies=set())
async def handle_validation_response(ctx: Context, sender: str, msg: ValidationResponse):
    """Collects peer responses, and on consensus, triggers all final actions."""
    event_id = msg.event_id
    
    async with PENDING_LOCK:
        if event_id not in pending_events: return
        
        event = pending_events[event_id]
        
        response_digest = get_digest({"event_id": msg.event_id, "validated": msg.validated})
        try:
            sender_pub_key = PublicKey(bytes.fromhex(msg.public_key))
            if not sender_pub_key.verify(response_digest, bytes.fromhex(msg.signature)):
                ctx.logger.warning(f"INVALID SIGNATURE on response from {sender}. Discarding.")
                return
        except Exception as e:
            ctx.logger.error(f"Signature verification failed for response from {sender}: {e}"); return

        event["responses"].append(msg)
        
        raw_data = event["raw_data"]
        registered_location = read_registry()[raw_data['device_id']]
        local_group = get_local_peer_group(registered_location)
        
        num_peers_in_group = len(local_group) - 1
        #if num_peers_in_group <= 0: return

        positive_responses = sum(1 for res in event["responses"] if res.validated)
        
        if positive_responses >= math.ceil(num_peers_in_group * QUORUM_RATIO):
            ctx.logger.info(f"CONSENSUS REACHED for event {event_id}. Triggering final actions.")
            await final_actions_after_consensus(ctx, event, registered_location)
            del pending_events[event_id]
        
        elif len(event["responses"]) >= num_peers_in_group:
            ctx.logger.warning(f"CONSENSUS FAILED for event {event_id}.")

            # --- Failure Handling ---
            mac_address = event["raw_data"]["device_id"]

            # Increment failure count
            SENSOR_FAILURE_COUNTS[mac_address] = SENSOR_FAILURE_COUNTS.get(mac_address, 0) + 1
            ctx.logger.warning(
                f"Failure count for {mac_address}: {SENSOR_FAILURE_COUNTS[mac_address]}/{FAILURE_THRESHOLD}"
            )

            # If threshold exceeded → cleanup
            if SENSOR_FAILURE_COUNTS[mac_address] >= FAILURE_THRESHOLD:
                cleanup_sensor_and_agent(mac_address)
                ctx.logger.error(
                    f"Sensor {mac_address} exceeded failure threshold. Cleanup triggered."
                )
                SENSOR_FAILURE_COUNTS[mac_address] = 0  # reset after cleanup

            # Remove pending event
            del pending_events[event_id]


# --- Main Execution ---
if __name__ == "__main__":
    agent.include(validation_protocol)
    print(f"[{AGENT_NAME}] Starting worker agent for MAC {MAC_ADDRESS} at {agent.address}")
    agent.run()

