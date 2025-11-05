"""
Pydantic models for Jira API responses.

This module contains the complete Pydantic model hierarchy representing
the structure of Jira issue responses from the API.
"""

from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field
from datetime import datetime


class JiraStatus(BaseModel):
    """Represents the status of a Jira issue."""
    name: str
    category: Optional[str] = None
    color: Optional[str] = None


class JiraPriority(BaseModel):
    """Represents the priority of a Jira issue."""
    name: str


class JiraUser(BaseModel):
    """Represents a Jira user (assignee, reporter, etc.)."""
    display_name: str
    name: str
    email: str
    avatar_url: Optional[str] = None


class JiraResponse(BaseModel):
    """
    Complete Pydantic model representing a Jira issue response.
    
    This model captures the essential fields returned by the Jira API
    for issue queries, including status, priority, assignee, reporter,
    and other metadata.
    """
    
    # Core issue fields
    id: str = Field(..., description="Unique identifier for the Jira issue")
    key: str = Field(..., description="Issue key (e.g., CBP-8446)")
    summary: str = Field(..., description="Issue title/summary")
    description: Optional[str] = Field(None, description="Detailed description of the issue")
    
    # Status and priority
    status: JiraStatus = Field(..., description="Current status of the issue")
    priority: JiraPriority = Field(..., description="Priority level of the issue")
    
    # People
    assignee: Optional[JiraUser] = Field(None, description="User assigned to the issue")
    reporter: JiraUser = Field(..., description="User who reported the issue")
    
    # Metadata
    labels: List[str] = Field(default_factory=list, description="Labels associated with the issue")
    created: str = Field(..., description="ISO timestamp when the issue was created")
    updated: str = Field(..., description="ISO timestamp when the issue was last updated")
    
    # Additional fields that might be present in extended responses
    project: Optional[Dict[str, Any]] = Field(None, description="Project information")
    issue_type: Optional[Dict[str, Any]] = Field(None, alias="issuetype", description="Issue type information")
    resolution: Optional[Dict[str, Any]] = Field(None, description="Resolution information if resolved")
    components: Optional[List[Dict[str, Any]]] = Field(None, description="Components associated with the issue")
    fix_versions: Optional[List[Dict[str, Any]]] = Field(None, alias="fixVersions", description="Fix versions")
    affects_versions: Optional[List[Dict[str, Any]]] = Field(None, alias="versions", description="Affected versions")
    
    # Time tracking
    time_estimate: Optional[int] = Field(None, alias="timeestimate", description="Time estimate in seconds")
    time_original_estimate: Optional[int] = Field(None, alias="timeoriginalestimate", description="Original time estimate in seconds")
    time_spent: Optional[int] = Field(None, alias="timespent", description="Time spent in seconds")
    
    # Dates
    due_date: Optional[str] = Field(None, alias="duedate", description="Due date if set")
    resolution_date: Optional[str] = Field(None, alias="resolutiondate", description="Resolution date if resolved")
    
    # Comments and attachments (if expanded)
    comments: Optional[Dict[str, Any]] = Field(None, description="Comments if expanded")
    attachments: Optional[List[Dict[str, Any]]] = Field(None, description="Attachments if expanded")
    
    # Workflow
    transitions: Optional[List[Dict[str, Any]]] = Field(None, description="Available transitions if expanded")
    
    # Custom fields - using a flexible approach for the many custom fields
    custom_fields: Optional[Dict[str, Any]] = Field(None, description="Custom fields with dynamic keys")
    
    # Subtasks and links
    subtasks: Optional[List[Dict[str, Any]]] = Field(None, description="Subtasks if present")
    issue_links: Optional[List[Dict[str, Any]]] = Field(None, alias="issuelinks", description="Issue links if present")
    
    # Epic information
    epic_link: Optional[str] = Field(None, description="Epic link if issue is part of an epic")
    epic_name: Optional[str] = Field(None, description="Epic name if this is an epic")
    
    # Sprint information (for Agile boards)
    sprint: Optional[Union[str, List[Dict[str, Any]]]] = Field(None, description="Sprint information")
    
    # Story points and estimation
    story_points: Optional[float] = Field(None, description="Story points if set")
    
    # Security level
    security: Optional[Dict[str, Any]] = Field(None, description="Security level if set")
    
    # Environment
    environment: Optional[str] = Field(None, description="Environment information")
    
    # Votes and watchers
    votes: Optional[Dict[str, Any]] = Field(None, description="Votes information")
    watchers: Optional[Dict[str, Any]] = Field(None, description="Watchers information")
    
    # Progress
    progress: Optional[Dict[str, Any]] = Field(None, description="Progress information")
    aggregate_progress: Optional[Dict[str, Any]] = Field(None, alias="aggregateprogress", description="Aggregate progress")
    
    # Work log
    worklog: Optional[Dict[str, Any]] = Field(None, description="Work log entries")
    
    class Config:
        """Pydantic configuration."""
        populate_by_name = True
        extra = "allow"  # Allow additional fields not explicitly defined
        
    def __str__(self) -> str:
        """String representation of the Jira issue."""
        return f"JiraResponse(key={self.key}, summary={self.summary[:50]}...)"
    
    def __repr__(self) -> str:
        """Detailed string representation."""
        return f"JiraResponse(id={self.id}, key={self.key}, status={self.status.name}, assignee={self.assignee.display_name if self.assignee else 'Unassigned'})"


class JiraSearchResponse(BaseModel):
    """
    Represents a response from Jira search API containing multiple issues.
    """
    
    expand: Optional[str] = Field(None, description="Fields that were expanded in the response")
    start_at: int = Field(0, alias="startAt", description="Starting index of results")
    max_results: int = Field(50, alias="maxResults", description="Maximum results per page")
    total: int = Field(..., description="Total number of issues matching the query")
    issues: List[JiraResponse] = Field(..., description="List of Jira issues")
    
    class Config:
        """Pydantic configuration."""
        populate_by_name = True


class JiraErrorResponse(BaseModel):
    """
    Represents an error response from Jira API.
    """
    
    error_messages: Optional[List[str]] = Field(None, alias="errorMessages", description="General error messages")
    errors: Optional[Dict[str, str]] = Field(None, description="Field-specific errors")
    
    class Config:
        """Pydantic configuration."""
        populate_by_name = True
