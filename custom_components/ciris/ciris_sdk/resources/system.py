"""
System resource for CIRIS v1 API (Pre-Beta).

Consolidates health, time, resources, runtime control, services, and shutdown
into a unified system operations interface matching API v3.0.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from ..transport import Transport


# Request/Response Models

class SystemHealthResponse(BaseModel):
    """Overall system health status."""
    status: str = Field(..., description="Overall health status (healthy/degraded/critical)")
    version: str = Field(..., description="System version")
    uptime_seconds: float = Field(..., description="System uptime in seconds")
    services: Dict[str, Dict[str, int]] = Field(..., description="Service health summary")
    initialization_complete: bool = Field(..., description="Whether system initialization is complete")
    cognitive_state: Optional[str] = Field(None, description="Current cognitive state if available")
    timestamp: datetime = Field(..., description="Current server time")


class TimeSyncStatus(BaseModel):
    """Time synchronization status."""
    synchronized: bool = Field(..., description="Whether time is synchronized")
    drift_ms: float = Field(..., description="Time drift in milliseconds")
    last_sync: datetime = Field(..., description="Last sync timestamp")


class SystemTimeResponse(BaseModel):
    """System and agent time information with timezone details."""
    system_time: datetime = Field(..., description="Host system time (OS time) in UTC")
    agent_time: datetime = Field(..., description="Agent's TimeService time in UTC")
    server_timezone: Optional[str] = Field(default="UTC", description="Server's local timezone (e.g., 'America/New_York')")
    utc_offset: Optional[str] = Field(default="+00:00", description="Current UTC offset (e.g., '-05:00')")
    is_dst: Optional[bool] = Field(default=False, description="Whether daylight saving time is active")
    uptime_seconds: float = Field(..., description="Service uptime in seconds")
    time_sync: TimeSyncStatus = Field(..., description="Time synchronization status")


class ResourceSnapshot(BaseModel):
    """Current resource usage snapshot."""
    memory_mb: float = Field(..., description="Memory usage in MB")
    cpu_percent: float = Field(..., description="CPU usage percentage")
    open_files: Optional[int] = Field(default=0, description="Number of open files")
    threads: Optional[int] = Field(default=0, description="Number of threads")
    timestamp: Optional[datetime] = Field(default=None, description="When snapshot was taken")


class ResourceBudget(BaseModel):
    """Resource limits/budget."""
    max_memory_mb: Optional[float] = Field(default=None, description="Maximum memory in MB")
    max_cpu_percent: Optional[float] = Field(default=None, description="Maximum CPU percentage")
    max_open_files: Optional[int] = Field(default=None, description="Maximum open files")
    max_threads: Optional[int] = Field(default=None, description="Maximum threads")
    
    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "ResourceBudget":
        """Convert API response format to ResourceBudget."""
        if "memory_mb" in data and isinstance(data["memory_mb"], dict):
            # Handle nested format from API
            return cls(
                max_memory_mb=data["memory_mb"].get("limit"),
                max_cpu_percent=data.get("cpu_percent", {}).get("limit"),
                max_open_files=data.get("open_files", {}).get("limit"),
                max_threads=data.get("threads", {}).get("limit")
            )
        # Handle flat format
        return cls(**data)


class ResourceUsageResponse(BaseModel):
    """System resource usage and limits."""
    current_usage: ResourceSnapshot = Field(..., description="Current resource usage")
    limits: ResourceBudget = Field(..., description="Configured resource limits")
    health_status: str = Field(..., description="Resource health (healthy/warning/critical)")
    warnings: List[str] = Field(default_factory=list, description="Resource warnings")
    critical: List[str] = Field(default_factory=list, description="Critical resource issues")


class RuntimeControlResponse(BaseModel):
    """Response to runtime control actions."""
    success: bool = Field(..., description="Whether action succeeded")
    message: str = Field(..., description="Human-readable status message")
    processor_state: str = Field(..., description="Current processor state")
    cognitive_state: Optional[str] = Field(None, description="Current cognitive state")
    queue_depth: int = Field(0, description="Number of items in processing queue")


class ServiceMetrics(BaseModel):
    """Service-specific metrics."""
    requests_total: Optional[int] = None
    requests_failed: Optional[int] = None
    average_latency_ms: Optional[float] = None
    custom_metrics: Optional[Dict[str, Any]] = Field(default_factory=dict)


class ServiceStatus(BaseModel):
    """Individual service status."""
    name: str = Field(..., description="Service name")
    type: str = Field(..., description="Service type")
    healthy: bool = Field(..., description="Whether service is healthy")
    available: bool = Field(..., description="Whether service is available")
    uptime_seconds: Optional[float] = Field(None, description="Service uptime if tracked")
    metrics: ServiceMetrics = Field(default_factory=ServiceMetrics, description="Service-specific metrics")


class ServicesStatusResponse(BaseModel):
    """Status of all system services."""
    services: List[ServiceStatus] = Field(..., description="List of service statuses")
    total_services: int = Field(..., description="Total number of services")
    healthy_services: int = Field(..., description="Number of healthy services")
    timestamp: datetime = Field(..., description="When status was collected")


class ShutdownResponse(BaseModel):
    """Response to shutdown request."""
    success: bool = Field(..., description="Whether shutdown was initiated")
    message: str = Field(..., description="Status message")
    grace_period_seconds: int = Field(..., description="Grace period before shutdown")


class SystemResource:
    """
    Consolidated system operations for v1 API (Pre-Beta).
    
    Combines health, time, resources, runtime control, services, and shutdown
    into a single resource matching the simplified API structure.
    
    Note: This replaces the old separate endpoints for telemetry, services,
    runtime, resources, time, and shutdown.
    """
    
    def __init__(self, transport: Transport) -> None:
        self._transport = transport
    
    async def health(self) -> SystemHealthResponse:
        """
        Get overall system health.
        
        Returns comprehensive health status including services and cognitive state.
        Requires: OBSERVER role
        """
        result = await self._transport.request("GET", "/v1/system/health")
        return SystemHealthResponse(**result)
    
    async def time(self) -> SystemTimeResponse:
        """
        Get system and agent time information.
        
        Shows both OS time and agent's TimeService time, useful for
        understanding time drift and synchronization status.
        Requires: OBSERVER role
        """
        result = await self._transport.request("GET", "/v1/system/time")
        return SystemTimeResponse(**result)
    
    async def resources(self) -> ResourceUsageResponse:
        """
        Get current resource usage and limits.
        
        Returns detailed resource metrics and health status.
        Requires: OBSERVER role
        """
        result = await self._transport.request("GET", "/v1/system/resources")
        
        # Handle limits conversion
        if "limits" in result and isinstance(result["limits"], dict):
            result["limits"] = ResourceBudget.from_api_response(result["limits"])
            
        # Handle current_usage conversion
        if "current_usage" in result and isinstance(result["current_usage"], dict):
            # Ensure missing fields have defaults
            current = result["current_usage"]
            if "open_files" not in current:
                current["open_files"] = 0
            if "threads" not in current:
                current["threads"] = 0
            if "timestamp" not in current:
                current["timestamp"] = datetime.now(timezone.utc).isoformat()
                
        return ResourceUsageResponse(**result)
    
    async def runtime_control(self, action: str, reason: Optional[str] = None) -> RuntimeControlResponse:
        """
        Control runtime operations.
        
        Args:
            action: Action to perform ('pause', 'resume', 'state')
            reason: Optional reason for the action
            
        Requires: ADMIN role
        """
        body = {"reason": reason} if reason else {}
        result = await self._transport.request(
            "POST", 
            f"/v1/system/runtime/{action}",
            json=body
        )
        return RuntimeControlResponse(**result)
    
    async def services(self) -> ServicesStatusResponse:
        """
        Get status of all system services.
        
        Returns detailed status for all 19 services.
        Requires: OBSERVER role
        """
        result = await self._transport.request("GET", "/v1/system/services")
        return ServicesStatusResponse(**result)
    
    async def shutdown(self, reason: str, grace_period_seconds: int = 30, force: bool = False) -> ShutdownResponse:
        """
        Request graceful system shutdown.
        
        Args:
            reason: Reason for shutdown
            grace_period_seconds: Time to wait before shutdown (default: 30)
            force: Whether to force immediate shutdown
            
        Requires: ADMIN role
        
        Note: For emergency shutdown with cryptographic signatures, use
        the EmergencyResource instead.
        """
        result = await self._transport.request(
            "POST",
            "/v1/system/shutdown",
            json={
                "reason": reason,
                "grace_period_seconds": grace_period_seconds,
                "force": force
            }
        )
        return ShutdownResponse(**result)
    
    # Convenience methods
    
    async def pause(self, reason: Optional[str] = None) -> RuntimeControlResponse:
        """Pause agent processing. Requires: ADMIN role"""
        return await self.runtime_control("pause", reason)
    
    async def resume(self, reason: Optional[str] = None) -> RuntimeControlResponse:
        """Resume agent processing. Requires: ADMIN role"""
        return await self.runtime_control("resume", reason)
    
    async def get_state(self) -> RuntimeControlResponse:
        """Get current runtime state. Requires: OBSERVER role"""
        return await self.runtime_control("state")
    
    async def is_healthy(self) -> bool:
        """Quick health check - returns True if system is healthy."""
        try:
            health = await self.health()
            return health.status == "healthy"
        except:
            return False