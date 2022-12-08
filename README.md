# Logreader
Simple python-script I use to analyze log-files to quickly extract the commonly relevant error-messages. The script prints the results to terminal and by default outputs to file `outfile.txt`.

## Usage
Running the script with `python logreader.py` and selecting the logfile to be analyzed. The following can be adjusted:

`display_separator`:   (True/false) Whether or not to display separators between errors in format "error:".  
`write_to_file`:       (True/false) Writing to a file or just terminal.  
`general_limit`:       Optional. Overrides the specific limits and sets a general limit of outputted errors. (Default: No limit)  
`context`:             Optional. The number of error-messages written above and below the output messages "error:". (Default: 3)  

`generic_display_separator`:   (True/false) Whether or not to display separators between generic errors.  
`generic_context`:             Optional. The number of error-messages written above and below generic errors. (Default: 0)  

You can also optionally enter one to three entries for `custom pattern` which returns case insensitive hits on the pattern. There is also a toggle for optional patterns to be searched, only two are enabled by default.