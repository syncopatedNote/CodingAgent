#!/usr/bin/env python3
"""
Code generation and reflection component for agent workflows
"""

from typing import Any
from langgraph.types import Command
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from .base_state import BaseState
from logger import setup_logger

logger = setup_logger()


class CodeGenerator:
    """Handles code generation and reflection for agent workflows"""

    def __init__(self, llm: Any):
        self.llm = llm

    async def generate_code(self, state: BaseState) -> Command:
        """Generate code based on design and development rules"""
        try:
            ticket_data = state["jira_ticket_data"]
            design_content = state["confluence_design_content"]
            dev_rules = state["development_rules"]
            
            # Get current iteration count
            reflection_count = state.get("reflection_count", 0)
            previous_feedback = state.get("reflection_feedback", "")

            ticket_summary = ticket_data.get("fields", {}).get("summary", "summary not available")
            ticket_description = ticket_data.get("fields", {}).get("description", "description not available")

            enhanced_context_section = ""
            if state.get('enhanced_context'):
                enhanced_context_section = f"""
                    ENHANCED CONTEXT:
                    {state['enhanced_context']}

                """

            # Include feedback from previous reflection if this is not the first iteration
            feedback_section = ""
            if reflection_count > 0 and previous_feedback:
                feedback_section = f"""
                    PREVIOUS REFLECTION FEEDBACK (Iteration {reflection_count}):
                    {previous_feedback}
                    
                    Please address all the feedback points in your improved code generation.
                """

            system_prompt = f"""
                You are an expert software developer. {'Generate' if reflection_count == 0 else 'Improve the'} high-quality code based on the following:

                DEVELOPMENT RULES:
                {dev_rules}

                JIRA TICKET DETAILS:
                Summary: {ticket_summary}
                Description: {ticket_description}

                DESIGN SPECIFICATIONS:
                {design_content}

                {enhanced_context_section}{feedback_section}Please {'generate' if reflection_count == 0 else 'improve the'} complete, production-ready code that:
                1. Follows the provided development rules strictly
                2. Implements the requirements from the Jira ticket
                3. Adheres to the design specifications from Confluence
                4. Includes proper error handling, logging, and documentation
                5. Follows best practices for the target technology stack
                {'6. Addresses all feedback points from the previous reflection' if reflection_count > 0 else ''}

                Provide the code with clear file structure and explanations.
                """

            user_message = "Generate the code for this requirement." if reflection_count == 0 else "Improve the code based on the reflection feedback."

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message)
            ]

            response = self.llm.invoke(messages)
            generated_code = response.content

            # Initialize reflection count if this is the first generation
            if reflection_count == 0:
                reflection_count = 0

            return Command(
                goto="reflect_code",
                update={
                    "generated_code": generated_code,
                    "reflection_count": reflection_count,
                    "workflow_status": f"code_generated_iteration_{reflection_count + 1}",
                    "messages": state["messages"] + [
                        AIMessage(content=f"Successfully {'generated' if reflection_count == 0 else 'improved'} code (iteration {reflection_count + 1})")
                    ]
                }
            )

        except Exception as e:
            logger.exception("Error generating Code: Traceback is")
            return Command(
                goto="handle_error",
                update={
                    "error_message": f"Error generating code: {str(e)}",
                    "workflow_status": "error"
                }
            )

    async def reflect_code(self, state: BaseState, max_iterations: int = 3) -> Command:
        """Review generated code and provide feedback for improvement"""
        try:
            reflection_count = state.get("reflection_count", 0)
            
            # Check if we've completed the maximum number of reflection cycles
            if reflection_count >= max_iterations:
                return Command(
                    goto="create_gitlab_branch",
                    update={
                        "workflow_status": "reflection_completed",
                        "messages": state["messages"] + [
                            AIMessage(content=f"Code reflection and improvement cycle completed after {max_iterations} iterations. Code is ready for commit.")
                        ]
                    }
                )

            ticket_data = state["jira_ticket_data"]
            design_content = state["confluence_design_content"]
            dev_rules = state["development_rules"]
            generated_code = state["generated_code"]

            ticket_summary = ticket_data.get("fields", {}).get("summary", "")
            ticket_description = ticket_data.get("fields", {}).get("description", "")

            reflection_prompt = f"""
                You are a senior code reviewer. Review the following generated code against the requirements and provide clear, actionable feedback.

                DEVELOPMENT RULES:
                {dev_rules}

                JIRA TICKET REQUIREMENTS:
                Summary: {ticket_summary}
                Description: {ticket_description}

                DESIGN SPECIFICATIONS:
                {design_content}

                GENERATED CODE (Iteration {reflection_count + 1}):
                {generated_code}

                Provide specific, actionable feedback on:
                1. Code quality and best practices adherence
                2. Requirements compliance from the Jira ticket
                3. Design specification alignment
                4. Security and error handling
                5. Performance considerations
                6. Code structure and maintainability
                7. Documentation and comments
                8. Specific improvements needed

                Be direct and actionable in your recommendations. Focus on concrete improvements that can be made.
                If the code is already good quality, still provide suggestions for potential enhancements.
                """

            messages = [
                SystemMessage(content=reflection_prompt),
                HumanMessage(content="Review this code and provide detailed feedback for improvement.")
            ]

            response = self.llm.invoke(messages)
            feedback = response.content

            # Increment reflection count and route back to generate_code for improvement
            return Command(
                goto="generate_code",
                update={
                    "reflection_feedback": feedback,
                    "reflection_count": reflection_count + 1,
                    "workflow_status": f"reflection_completed_iteration_{reflection_count + 1}",
                    "messages": state["messages"] + [
                        AIMessage(content=f"Code reflection iteration {reflection_count + 1} completed. Feedback provided for code improvement.")
                    ]
                }
            )

        except Exception as e:
            logger.exception("Error in code reflection: Traceback is")
            return Command(
                goto="handle_error",
                update={
                    "error_message": f"Error in code reflection: {str(e)}",
                    "workflow_status": "error"
                }
            )
