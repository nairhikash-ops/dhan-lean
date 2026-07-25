#
#   LEAN Docker Container 20200522
#   Cross platform deployment for multiple brokerages
#

# Use base system
FROM quantconnect/lean:foundation

MAINTAINER QuantConnect <contact@quantconnect.com>

#Install debugpy and PyDevD for remote python debugging
RUN pip install --no-cache-dir ptvsd==4.3.2 debugpy~=1.6.7 pydevd-pycharm~=231.9225.15

# Install vsdbg for remote C# debugging in Visual Studio and Visual Studio Code
RUN wget https://aka.ms/getvsdbgsh -O - 2>/dev/null | /bin/sh /dev/stdin -v 17.10.20209.7 -l /root/vsdbg

COPY ./DataLibraries /Lean/Launcher/bin/Debug/
# Copy global metadata databases explicitly without bundling sample price history archives
COPY ./Lean/Data/market-hours/ /Lean/Data/market-hours/
COPY ./Lean/Data/symbol-properties/ /Lean/Data/symbol-properties/
# Note: Temporary provider-normalized LEAN exports may be mounted under /Lean/Data/equity/india.
# The complete /Lean/Data directory must not be replaced by a bind mount because that would hide global metadata.
RUN mkdir -p /Lean/Data/equity/india/minute /Lean/Data/equity/india/daily /Lean/Data/equity/india/map_files /Lean/Data/equity/india/factor_files
COPY ./Lean/Launcher/bin/Debug/ /Lean/Launcher/bin/Debug/
COPY ./Lean/Optimizer.Launcher/bin/Debug/ /Lean/Optimizer.Launcher/bin/Debug/
COPY ./Lean/Report/bin/Debug/ /Lean/Report/bin/Debug/
COPY ./Lean/DownloaderDataProvider/bin/Debug/ /Lean/DownloaderDataProvider/bin/Debug/

# Can override with '-w'
WORKDIR /Lean/Launcher/bin/Debug

ENTRYPOINT [ "dotnet", "QuantConnect.Lean.Launcher.dll" ]
