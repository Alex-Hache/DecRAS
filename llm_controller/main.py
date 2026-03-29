"""Main reasoning loop — LLM observes, decides, acts, repeats."""

import asyncio
import json
import logging
import sys
import time

from llm_controller.config import MAX_STEPS, HISTORY_WINDOW
from llm_controller.llm import LLM
from llm_controller.mcp_client import MCPClient
from llm_controller.prompt import build_messages, parse_response
from mcp_server.interaction_log import InteractionLog

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_TASK = "Pick up the red cup and place it on the blue plate."


async def run_loop(task: str | None = None):
    task = task or DEFAULT_TASK
    logger.info("=" * 60)
    logger.info("TASK: %s", task)
    logger.info("=" * 60)

    # Initialize
    llm = LLM()
    client = MCPClient()
    await client.connect()

    interaction_log = InteractionLog(task=task)
    history: list[dict] = []
    retries = 0
    max_retries = 2
    success = False
    final_reason = "max_steps_reached"
    loop_start = time.time()

    try:
        # Start episode recording
        await client.call_tool("start_episode", {"task": task})

        for step in range(1, MAX_STEPS + 1):
            step_start = time.time()
            logger.info("─── Step %d/%d ───", step, MAX_STEPS)

            # Build prompt
            messages = build_messages(task, history, window=HISTORY_WINDOW)

            # Generate LLM response
            t0 = time.time()
            response_text = llm.generate(messages)
            llm_ms = (time.time() - t0) * 1000
            logger.info("LLM (%.0fms): %s", llm_ms, response_text.strip()[:300])

            # Parse response
            thought, action = parse_response(response_text)

            # DONE
            if action is None and "DONE" in response_text.upper():
                interaction_log.record_turn(
                    step=step, messages=messages, llm_response=response_text,
                    thought=thought, tool_name=None, tool_args=None,
                    tool_result=None, llm_latency_ms=llm_ms,
                )
                success = True
                final_reason = "task_complete"
                logger.info("TASK COMPLETE in %d steps (%.1fs total)",
                            step, time.time() - loop_start)
                break

            # Parse failure — retry
            if action is None:
                retries += 1
                interaction_log.record_parse_failure(step=step, llm_response=response_text)
                logger.warning("PARSE FAILURE %d/%d: %s",
                               retries, max_retries, response_text[:100])
                if retries > max_retries:
                    final_reason = "parse_failures"
                    logger.error("Too many parse failures, aborting")
                    break
                history.append({
                    "thought": thought or "(parse failure)",
                    "action_text": "(invalid)",
                    "result": {"error": "Could not parse your action"},
                    "scene": history[-1]["scene"] if history else None,
                })
                continue

            retries = 0

            # Execute action via MCP
            action_text = f"{action.name}({', '.join(f'{k}={v!r}' for k, v in action.arguments.items())})"
            logger.info("ACTION: %s", action_text)
            if thought:
                logger.info("THOUGHT: %s", thought[:200])

            t0 = time.time()
            result = await client.call_tool(action.name, action.arguments)
            action_ms = (time.time() - t0) * 1000
            logger.info("RESULT (%.0fms): %s", action_ms, json.dumps(result))

            # Log the interaction turn
            interaction_log.record_turn(
                step=step, messages=messages, llm_response=response_text,
                thought=thought, tool_name=action.name, tool_args=action.arguments,
                tool_result=result, llm_latency_ms=llm_ms, tool_latency_ms=action_ms,
            )

            # Auto-observe after every non-observe action
            if action.name != "observe":
                scene = await client.call_tool("observe")
            else:
                scene = result
                result = {"status": "observed"}

            # Append to history
            history.append({
                "thought": thought,
                "action_text": action_text,
                "result": result,
                "scene": scene,
            })

            step_ms = (time.time() - step_start) * 1000
            logger.info("STEP %d total: %.0fms (llm=%.0fms, action=%.0fms)",
                        step, step_ms, llm_ms, action_ms)

        else:
            logger.warning("Reached max steps (%d) without completing task", MAX_STEPS)

    finally:
        # End episode recording
        await client.call_tool("end_episode", {
            "success": success,
            "reason": final_reason,
        })
        await client.disconnect()

        # Finalize interaction log
        interaction_log.finish(success=success, reason=final_reason)

    total_time = time.time() - loop_start
    logger.info("=" * 60)
    logger.info("RUN COMPLETE: success=%s reason=%s steps=%d time=%.1fs",
                success, final_reason, len(history), total_time)
    logger.info("=" * 60)

    return history


def main():
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else DEFAULT_TASK
    asyncio.run(run_loop(task))


if __name__ == "__main__":
    main()
