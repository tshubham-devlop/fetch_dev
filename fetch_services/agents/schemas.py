# from uagents import Model
# from typing import List, Dict

# # 1. Simplified raw data packet sent from a sensor's gateway to its agent.
# # Contains only the essential real-time information.
# class SensorData(Model):
#     device_id: str      # The MAC address of the sensor hardware
#     timestamp: str      # The ISO 8601 timestamp of the reading
#     decibel: float      # The measured sound level
#     # sound_features are removed as per the new simplified model

# # 2. Internal P2P message for local consensus (remains the same)
# class ValidationRequest(Model):
#     event_id: str
#     location: Dict[str, float]      
#     sound_class: str    
#     decibel: float      
#     public_key: str     
#     signature: str      

# # 3. Internal P2P response for local consensus (remains the same)
# class ValidationResponse(Model):
#     event_id: str
#     validated: bool
#     public_key: str     
#     signature: str      

# # 4. Final, high-value data object for external systems (remains the same)
# class EnrichedData(Model):
#     device_id: str
#     event: str          
#     decibel: float
#     timestamp: str
#     location: Dict[str, float]      
#     confidence: float   
#     validated: bool     
#     orchestrator_address: str 
#     validator_addresses: List[str] 
#     raw_data_ipfs_link: str 


# # 5. NEW: The message a worker agent sends to the Notary Agent after
# # a successful local consensus. This is the "fact" to be recorded.

# class ValidatedSensorData(Model):
#     """
#     A nested model containing the specific, validated data points
#     that will be added to the knowledge graph.
#     """
#     mac_address: str
#     timestamp: float # Unix timestamp
#     sound_level_db: float
#     location: Dict[str, float]

# class FactCandidate(Model):
#     """
#     The wrapper message that contains the validated event data.
#     This is what the Notary Agent will receive.
#     """
#     validated_event: ValidatedSensorData

from uagents import Model
from typing import List, Dict

# 1. Simplified raw data packet sent from a sensor's gateway to its agent.
# Contains only the essential real-time information.
class SensorData(Model):
    device_id: str      # The MAC address of the sensor hardware
    timestamp: str      # The ISO 8601 timestamp of the reading
    decibel: float      # The measured sound level

# 2. Internal P2P message for local consensus
class ValidationRequest(Model):
    event_id: str
    location: Dict[str, float]      
    sound_class: str    
    decibel: float      
    public_key: str     
    signature: str      

# 3. Internal P2P response for local consensus
class ValidationResponse(Model):
    event_id: str
    validated: bool
    public_key: str     
    signature: str      

# 4. A nested model containing the specific, validated data points
#    that will be sent to the Notary Agent.
class ValidatedSensorData(Model):
    mac_address: str
    timestamp: float # Unix timestamp
    sound_level_db: float
    location: Dict[str, float] # e.g., {"lat": 28.6, "lon": 77.2}

# 5. The wrapper message that contains the validated event data.
# This is what the Notary Agent receives.
class FactCandidate(Model):
    validated_event: ValidatedSensorData

# 6. The final, high-value data object for external systems like Fluence
class EnrichedData(Model):
    device_id: str
    event: str          
    decibel: float
    timestamp: str
    location: Dict[str, float]      
    confidence: float   
    validated: bool     
    orchestrator_address: str 
    validator_addresses: List[str] 
    raw_data_ipfs_link: str 





