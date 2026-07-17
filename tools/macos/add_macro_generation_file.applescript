-- Drag-and-drop app for adding a MACRO generation file to this project.
--
-- Source-controlled so any teammate can rebuild the same app locally with
-- `make build-macro-generation-dropper` -- do not hand-edit the compiled
-- .app bundle; edit this file and rebuild instead.
--
-- The app finds the project root from its own location, so it must stay at
-- tools/macos/Add MACRO Generation File.app inside the repository (a copy or
-- alias placed on the Desktop/Dock for convenience still works, since
-- aliases resolve back to this real location).

on getProjectRoot()
	set appPosixPath to POSIX path of (path to me)
	if appPosixPath ends with "/" then
		set appPosixPath to text 1 thru -2 of appPosixPath
	end if
	set toolsMacosDir to do shell script "dirname " & quoted form of appPosixPath
	set toolsDir to do shell script "dirname " & quoted form of toolsMacosDir
	set projectRoot to do shell script "dirname " & quoted form of toolsDir
	return projectRoot
end getProjectRoot

on ingestOneFile(projectRoot, filePosixPath)
	set pythonBin to projectRoot & "/.venv/bin/python"
	set cmd to "cd " & quoted form of projectRoot & ¬
		" && PYTHONPATH=src " & quoted form of pythonBin & ¬
		" -m nzk_aphiam.data.external.ingest_macro --source " & quoted form of filePosixPath & ¬
		" --kind generation 2>&1"
	return do shell script cmd
end ingestOneFile

on open theFiles
	set projectRoot to my getProjectRoot()
	repeat with oneFile in theFiles
		set filePosixPath to POSIX path of oneFile
		set fileName to do shell script "basename " & quoted form of filePosixPath
		try
			set outputText to my ingestOneFile(projectRoot, filePosixPath)
			display dialog "Added " & fileName & " to the project." & return & return & outputText ¬
				buttons {"OK"} default button "OK" with title "MACRO file added" with icon note
		on error errMsg
			display dialog "Could not add " & fileName & ":" & return & return & errMsg ¬
				buttons {"OK"} default button "OK" with title "MACRO file not added" with icon caution
		end try
	end repeat
end open

on run
	display dialog "Drag a MACRO generation file (CSV, Excel, or Parquet) onto this icon to add it to the project." ¬
		buttons {"OK"} default button "OK" with title "Add MACRO Generation File"
end run
