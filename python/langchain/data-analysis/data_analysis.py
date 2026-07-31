# Copyright 2025 Daytona Platforms Inc.
# SPDX-License-Identifier: Apache-2.0

"""LangChain data analysis example using Daytona sandboxes."""

import base64
import os

from dotenv import load_dotenv
from langchain.agents import create_agent  # pylint: disable=import-error
from langchain.chat_models import init_chat_model  # pylint: disable=import-error

# pylint: disable=import-error
from langchain_daytona_data_analysis import DaytonaDataAnalysisTool

from daytona import ExecutionArtifacts

load_dotenv()

# "provider:model" string, e.g. "fireworks:accounts/fireworks/models/kimi-k2p6".
# See the README for supported providers and their API keys.
MODEL = os.environ.get("MODEL", "anthropic:claude-sonnet-4-5-20250929")

model = init_chat_model(MODEL, temperature=0, max_retries=2)


def process_data_analysis_result(result: ExecutionArtifacts):
    # Print the standard output from code execution
    print("Result stdout", result.stdout)
    result_idx = 0
    for chart in result.charts:
        if chart.png:
            # Save the png to a file
            # The png is in base64 format.
            with open(f"chart-{result_idx}.png", "wb") as f:
                f.write(base64.b64decode(chart.png))
            print(f"Chart saved to chart-{result_idx}.png")
            result_idx += 1


def main():
    data_analysis_tool = DaytonaDataAnalysisTool(on_result=process_data_analysis_result)

    try:
        with open("./dataset.csv", "rb") as f:
            data_analysis_tool.upload_file(
                f,
                description=(
                    "This is a CSV file containing vehicle valuations. "
                    "Relevant columns:\n"
                    "- 'year': integer, the manufacturing year of the vehicle\n"
                    "- 'price_in_euro': float, the listed price "
                    "of the vehicle in Euros\n"
                    "Drop rows where 'year' or 'price_in_euro' is missing, "
                    "non-numeric, or an outlier."
                ),
            )

        agent = create_agent(model, tools=[data_analysis_tool], debug=True)

        agent.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "Analyze how vehicles price varies by "
                        "manufacturing year. Create a line chart showing "
                        "average price per year.",
                    }
                ]
            }
        )
    finally:
        data_analysis_tool.close()


if __name__ == "__main__":
    main()
