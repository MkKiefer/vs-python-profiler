"""The collector process: started by the extension with the target's interpreter.

It samples the target from the outside (Tachyon), keeps the profile store, talks
to the extension over JSON-RPC on stdio and receives what the in-process agent
(``_vscode_pyprof.target``) reports. Nothing here runs inside the profiled program.
"""
