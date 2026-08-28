import re
import os
from termcolor import colored
import PySimpleGUI as sg

from logreader_core import CategoryResult, SearchPattern, analyze_lines

#Log analysis

#TODO: Migrate to different GUI (maybe)
#TODO: Add support for several files in at once (maybe)
#TODO: Fix general display_separator to be only initialized when has context and remove from GUI for both
#TODO: Change default filewrite to off
#TODO: Investigate error in custom pattern on browser log (lim non contxt 20 delimiter) (fix: conv to lower)
#TODO: Implement nested search (search from the generated error-lists with custom input)
#TODO: Catch and handle file-encoding errors (see file encodingtest)

def name(name):

    dots = 23-len(name)-2
    return sg.Text(name + ' ' + '•'*dots, size=(23,1), justification='r',pad=(0,0), font='Courier 10')

def resultToDisplayRows(result: CategoryResult, display_separator: bool):

    rows = []
    for excerpt in result.excerpts:
        for line in excerpt.lines:
            line_number = str(line.number)
            spaces = " " * max(0, 7-len(line_number))
            rows.append(line_number + spaces + "-> " + line.text)
        if display_separator:
            rows.append("-------->")
    return rows

def printArrayResults(arrIn, msg, limit, has_limit, context, gen_line, err_num):

    print("------------------------------------------------")
    print(gen_line)
    print("------------------------------------------------")
    err_count = 0
    broken = False
    for i, x in enumerate(arrIn):
    
        regex_comp = re.split(r'([0-9]+ *->)', x, 1)
        isMsgArrow = (arrIn[i] == "-------->")
        
        if isMsgArrow:
            isMsgContained = False
            isErrorMsg = False
        else:
            isMsgContained = (msg.lower() in regex_comp[2].lower())
            isErrorMsg = (msg == "error") and ("error:" in(regex_comp[2].lower()))
        
        if not isMsgArrow and isMsgContained and not isErrorMsg:
            
            #Split into parts and print appropriate words in color. The format is simple:
            #1 - regex_comp[1] = The line-number in form "123  ->"
            #2 - rest_res[0]   = The string before the "error"-word
            #3 - warresword[0] = The error-word, retrieved to preserve case (ERROR: vs Error: etc)
            #4 - rest_res[1]   = The string after the "error"-word
            pattern = re.compile(re.escape(msg), re.IGNORECASE)
            warresword = re.findall(pattern, regex_comp[2])
            rest_res = re.split(pattern, regex_comp[2], 1)
            
            print(colored(regex_comp[1], "red", attrs=["bold"]) + colored(rest_res[0], 'green') + colored(warresword[0], "red") + colored(rest_res[1], 'green'))
            err_count += 1
        else:
            #Colors the linenum-arrow
            first_split = re.split(r'([0-9]+ *->)', x, 1)
            if(first_split[0] == "-------->"):
                print(x)
            else:
                print(colored(first_split[1], "blue", attrs=["bold"]) + first_split[2])
                
        if has_limit and (err_count == limit):
            
            #Print rest of context after error
            for h in range(context):
                if(((h + i) + 1) < len(arrIn)):
                    if msg.lower() in arrIn[(h + i) + 1].lower():
                        break
                    else:
                        res_split = re.split(r'([0-9]+ *->)', arrIn[(h + i) + 1], 1)
                        if(res_split[0] == "-------->"):
                            print(res_split[0])
                        else:
                            print(colored(res_split[1], "blue", attrs=["bold"]) + res_split[2])
                            
            insert_msg = "Limited, showing " + str(limit) + " out of " + str(err_num) + " elements.\n"
            print(colored(insert_msg, "blue", attrs=["bold"]))
            broken = True
            break
    if not broken:
        insert_msg = "Printed all " + str(err_num) + " elements.\n"
        print(colored(insert_msg, "blue", attrs=["bold"]))

def writeArrayResults(w, arrIn, limit, has_limit, gen_line, msg, err_num, context):

    err_count = 0
    broken = False
    
    w.write("------------------------------------------------\n")
    w.write(gen_line + "\n")
    w.write("------------------------------------------------\n")
    for i, x in enumerate(arrIn):
        
        regex_comp = re.split(r'([0-9]+ *->)', x, 1)
        
        isMsgArrow = (arrIn[i] == "-------->")
        if isMsgArrow:
            isMsgContained = False
            isErrorMsg = False
        else:
            isMsgContained = (msg.lower() in regex_comp[2].lower())
            isErrorMsg = (msg == "error") and ("error:" in(regex_comp[2].lower()))
        
        if not isMsgArrow and isMsgContained and not isErrorMsg:
            w.write(x + "\n")
            err_count += 1
        else:
            w.write(x + "\n")
        if has_limit and (err_count == limit):
                
            #Write rest of context after error
            for h in range(context):
                if(((h + i) + 1) < len(arrIn)):
                    if msg.lower() in arrIn[(h + i) + 1].lower():
                        break
                    else:
                        w.write(arrIn[(h + i) + 1] + "\n")
                
            w.write("\nLimited, showing " + str(limit) + " out of " + str(err_num) + " elements.\n\n")
            broken = True
            break 
    if not broken:
        w.write("\nPrinted all " + str(err_num) + " elements.\n\n")

def main():
    
    context = 3
    context_generic = 0
    
    display_separator = True
    display_separator_general = False
    write_to_file = True
    
    limit_output = 0
    limit_output_gen = 0
    limit_output_wargen = 0
    limit_output_failed = 0
    limit_output_fatal = 0
    
    general_limit = 0
    
    version = "Logreader v0.12"
    
    isFailedInitialized = True
    isFatalInitialized = True
    isWarningInitialized = False
    isFailureInitialized = False
    isIllegalInitialized = False
    isInvalidInitialized = False
    isExceptionInitialized = False
    isCriticalInitialized = False
    
    err_msg1 = "error:"    
    err_gen = "error"
    failed_gen = "failed"
    failure_gen = "failure"
    illegal_gen = "illegal"
    fatal_gen = "fatal"
    war_msg1 = "warning:"
    invalid_gen = "invalid"
    exception_gen = "exception:"
    critical_gen = "critical"
    cust_pattern = ""
    cust_pattern2 = ""
    cust_pattern3 = ""
    
    #PySimpleGUI file-select
    layout = [[sg.T("")], 
        [sg.Text("Choose a logfile: "), 
            sg.Input(key="-IN2-" , change_submits=True), 
            sg.FileBrowse(key="-IN-")],
        [sg.Button("Submit")]]
    
    window = sg.Window(version, layout, size=(535,115))
    while True:
        event, values = window.read()
        if event == sg.WIN_CLOSED or event=="Exit":
            break
        elif event == "Submit":
            filename = values["-IN-"]
            break
    
    #PySimpleGUI value-select  
    def_toggle_size = (21,1)
    def_box_size = (21,1)
    
    leftcol = [
        [sg.Text('')],
        [sg.Text(('Value Selection -'))],
        [sg.Text('')],
        [sg.Text(('Display separator'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_on, key='SEPARATOR', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=True),
            sg.Text('On')],
        [sg.Text(('Write to file'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_on, key='FILEWRITE', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=True),
            sg.Text('On')],
        [sg.Text(('Output error limit:'), size = def_box_size), 
            sg.Input(enable_events=True,  key='ERRIN', s=3),
            sg.Text("Default = Unlimited")],
        [sg.Text(('Context around errors:'), size = def_box_size), 
            sg.Input(enable_events=True,  key='CONTIN', s=3),
            sg.Text("Default = 3")],
        [sg.Text('')],
        [sg.Text(('Custom pattern 1:'), size = def_box_size), sg.Input(key='CUSTOMIN', s=19)],
        [sg.Text(('Custom pattern 2:'), size = def_box_size), sg.Input(key='CUSTOMIN2', s=19)],
        [sg.Text(('Custom pattern 3:'), size = def_box_size), sg.Input(key='CUSTOMIN3', s=19)],
        [sg.Text('')],
        [sg.Text(('Generic display separator'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_off, key='GENSEPARATOR', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=False),
            sg.Text('On')],
        [sg.Text(('Generic context:'), size = def_box_size), 
            sg.Input(enable_events=True,  key='GENCONTIN', s=3),
            sg.Text("Default = 0")],
        [sg.Text('')],
        [sg.Text('')],
        [sg.Text('')],
        [sg.Button("Submit")]
    ]
    
    rightcol = [
        [sg.Text('')],
        [sg.Text('Toggle Patterns -')],
        [sg.Text('')],
        [sg.Text(('Toggle All'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_off, key='TOGGLEALL', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=False),
            sg.Text('On')],
        [sg.Text('')],
        [sg.Text(('FAILED'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_on, key='FAILED', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=True),
            sg.Text('On')],
        [sg.Text(('FATAL'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_on, key='FATAL', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=True),
            sg.Text('On')],
        [sg.Text(('WARNING:'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_off, key='WARNING', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=False),
            sg.Text('On')],
        [sg.Text(('FAILURE'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_off, key='FAILURE', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=False),
            sg.Text('On')],
        [sg.Text(('ILLEGAL'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_off, key='ILLEGAL', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=False),
            sg.Text('On')],
        [sg.Text(('INVALID'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_off, key='INVALID', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=False),
            sg.Text('On')],
        [sg.Text(('EXCEPTION:'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_off, key='EXCEPTION', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=False),
            sg.Text('On')],
        [sg.Text(('CRITICAL'), size = def_toggle_size), sg.Text('Off'),
            sg.Button(image_data=toggle_btn_off, key='CRITICAL', button_color=(sg.theme_background_color(), sg.theme_background_color()), border_width=0, metadata=False),
            sg.Text('On')]
    ]
    
    colSize = (360, 550)
    layout = [
        [sg.Column(leftcol, size=colSize),
        sg.VSeperator(),
        sg.Column(rightcol, size=colSize)]
    ]
    
    toggledOnce = False    
    window.close()    
    window = sg.Window(version, layout, size=(770,575))
    while True:
        event, values = window.read()
        if event in (sg.WIN_CLOSED, 'Exit'):
            break
        elif event == 'SEPARATOR':
            window['SEPARATOR'].metadata = not window['SEPARATOR'].metadata
            window['SEPARATOR'].update(image_data=toggle_btn_on if window['SEPARATOR'].metadata else toggle_btn_off)
            display_separator = window['SEPARATOR'].metadata
        elif event == 'GENSEPARATOR':
            window['GENSEPARATOR'].metadata = not window['GENSEPARATOR'].metadata
            window['GENSEPARATOR'].update(image_data=toggle_btn_on if window['GENSEPARATOR'].metadata else toggle_btn_off)
            display_separator_general = window['GENSEPARATOR'].metadata
        elif event == 'FILEWRITE':
            window['FILEWRITE'].metadata = not window['FILEWRITE'].metadata
            window['FILEWRITE'].update(image_data=toggle_btn_on if window['FILEWRITE'].metadata else toggle_btn_off)
            write_to_file = window['FILEWRITE'].metadata
        elif event == 'TOGGLEALL':
            window['TOGGLEALL'].metadata = not window['TOGGLEALL'].metadata
            window['TOGGLEALL'].update(image_data=toggle_btn_on if window['TOGGLEALL'].metadata else toggle_btn_off)
            if not(toggledOnce):
                toggledOnce = True
            else:
                window['FAILED'].metadata = not window['FAILED'].metadata
                window['FAILED'].update(image_data=toggle_btn_on if window['FAILED'].metadata else toggle_btn_off)
                isFailedInitialized = window['FAILED'].metadata
                window['FATAL'].metadata = not window['FATAL'].metadata
                window['FATAL'].update(image_data=toggle_btn_on if window['FATAL'].metadata else toggle_btn_off)
                isFatalInitialized = window['FATAL'].metadata
            window['WARNING'].metadata = not window['WARNING'].metadata
            window['WARNING'].update(image_data=toggle_btn_on if window['WARNING'].metadata else toggle_btn_off)
            isWarningInitialized = window['WARNING'].metadata
            window['FAILURE'].metadata = not window['FAILURE'].metadata
            window['FAILURE'].update(image_data=toggle_btn_on if window['FAILURE'].metadata else toggle_btn_off)
            isFailureInitialized = window['FAILURE'].metadata
            window['ILLEGAL'].metadata = not window['ILLEGAL'].metadata
            window['ILLEGAL'].update(image_data=toggle_btn_on if window['ILLEGAL'].metadata else toggle_btn_off)
            isIllegalInitialized = window['ILLEGAL'].metadata
            window['INVALID'].metadata = not window['INVALID'].metadata
            window['INVALID'].update(image_data=toggle_btn_on if window['INVALID'].metadata else toggle_btn_off)
            isInvalidInitialized = window['INVALID'].metadata
            window['EXCEPTION'].metadata = not window['EXCEPTION'].metadata
            window['EXCEPTION'].update(image_data=toggle_btn_on if window['EXCEPTION'].metadata else toggle_btn_off)
            isExceptionInitialized = window['EXCEPTION'].metadata
            window['CRITICAL'].metadata = not window['CRITICAL'].metadata
            window['CRITICAL'].update(image_data=toggle_btn_on if window['CRITICAL'].metadata else toggle_btn_off)
            isCriticalInitialized = window['CRITICAL'].metadata
            
        elif event == 'FAILED':
            window['FAILED'].metadata = not window['FAILED'].metadata
            window['FAILED'].update(image_data=toggle_btn_on if window['FAILED'].metadata else toggle_btn_off)
            isFailedInitialized = window['FAILED'].metadata
        elif event == 'FATAL':
            window['FATAL'].metadata = not window['FATAL'].metadata
            window['FATAL'].update(image_data=toggle_btn_on if window['FATAL'].metadata else toggle_btn_off)
            isFatalInitialized = window['FATAL'].metadata
        elif event == 'WARNING':
            window['WARNING'].metadata = not window['WARNING'].metadata
            window['WARNING'].update(image_data=toggle_btn_on if window['WARNING'].metadata else toggle_btn_off)
            isWarningInitialized = window['WARNING'].metadata
        elif event == 'FAILURE':
            window['FAILURE'].metadata = not window['FAILURE'].metadata
            window['FAILURE'].update(image_data=toggle_btn_on if window['FAILURE'].metadata else toggle_btn_off)
            isFailureInitialized = window['FAILURE'].metadata
        elif event == 'ILLEGAL':
            window['ILLEGAL'].metadata = not window['ILLEGAL'].metadata
            window['ILLEGAL'].update(image_data=toggle_btn_on if window['ILLEGAL'].metadata else toggle_btn_off)
            isIllegalInitialized = window['ILLEGAL'].metadata
        elif event == 'INVALID':
            window['INVALID'].metadata = not window['INVALID'].metadata
            window['INVALID'].update(image_data=toggle_btn_on if window['INVALID'].metadata else toggle_btn_off)
            isInvalidInitialized = window['INVALID'].metadata
        elif event == 'EXCEPTION':
            window['EXCEPTION'].metadata = not window['EXCEPTION'].metadata
            window['EXCEPTION'].update(image_data=toggle_btn_on if window['EXCEPTION'].metadata else toggle_btn_off)
            isExceptionInitialized = window['EXCEPTION'].metadata
        elif event == 'CRITICAL':
            window['CRITICAL'].metadata = not window['CRITICAL'].metadata
            window['CRITICAL'].update(image_data=toggle_btn_on if window['CRITICAL'].metadata else toggle_btn_off)
            isCriticalInitialized = window['CRITICAL'].metadata
            
        elif event == 'CUSTOMIN':
            cust_pattern = values['CUSTOMIN']
        elif event == 'CUSTOMIN2':
            cust_pattern2 = values['CUSTOMIN2']
        elif event == 'CUSTOMIN3':
            cust_pattern3 = values['CUSTOMIN3']
            
        elif event == "Submit":
            display_separator = window['SEPARATOR'].metadata
            write_to_file = window['FILEWRITE'].metadata
            display_separator_general = window['GENSEPARATOR'].metadata
            cust_pattern = values['CUSTOMIN']
            cust_pattern2 = values['CUSTOMIN2']
            cust_pattern3 = values['CUSTOMIN3']
            isFailedInitialized = window['FAILED'].metadata
            isFatalInitialized = window['FATAL'].metadata
            isWarningInitialized = window['WARNING'].metadata
            isFailureInitialized = window['FAILURE'].metadata
            isIllegalInitialized = window['ILLEGAL'].metadata
            isInvalidInitialized = window['INVALID'].metadata
            isExceptionInitialized = window['EXCEPTION'].metadata
            isCriticalInitialized = window['CRITICAL'].metadata
            
            if values['GENCONTIN'] != '':
                context_generic = int(values['GENCONTIN'])            
            if values['ERRIN'] != '':
                general_limit = int(values['ERRIN'])
            if values['CONTIN'] != '':
                context = int(values['CONTIN'])                
            break
            
        elif event == 'ERRIN' and len(values['ERRIN']) and values['ERRIN'][-1] not in ('0123456789'):
            window['ERRIN'].update(values['ERRIN'][:-1])
        elif event == 'CONTIN' and len(values['CONTIN']) and values['CONTIN'][-1] not in ('0123456789'):
            window['CONTIN'].update(values['CONTIN'][:-1])
        elif event == 'GENCONTIN' and len(values['GENCONTIN']) and values['GENCONTIN'][-1] not in ('0123456789'):
            window['GENCONTIN'].update(values['GENCONTIN'][:-1])
    window.close()
    
    custIsInitiated = (cust_pattern != "")
    custIsInitiated2 = (cust_pattern2 != "")
    custIsInitiated3 = (cust_pattern3 != "")
    
    if(general_limit != 0):
        limit_output = general_limit
        limit_output_gen = general_limit
        limit_output_wargen = general_limit
        limit_output_failed = general_limit
        limit_output_fatal = general_limit
    
    has_limit = (limit_output != 0)
    has_limit_gen = (limit_output_gen != 0)        
    has_limit_wargen = (limit_output_wargen != 0)
    has_limit_failed = (limit_output_failed != 0)
    has_limit_fatal = (limit_output_fatal != 0)

    #Reading
    f = open(filename, "r")
    if write_to_file:
        w = open("outfile.txt", "w")
        
    logoutput = f.read().splitlines()

    search_patterns = [
        SearchPattern("error_colon", err_msg1, context),
        SearchPattern(
            "error",
            err_gen,
            context_generic,
            excluded_substrings=(err_msg1,),
        ),
    ]
    optional_patterns = [
        (isFailedInitialized, "failed", failed_gen),
        (isFatalInitialized, "fatal", fatal_gen),
        (isWarningInitialized, "warning", war_msg1),
        (isFailureInitialized, "failure", failure_gen),
        (isIllegalInitialized, "illegal", illegal_gen),
        (isInvalidInitialized, "invalid", invalid_gen),
        (isExceptionInitialized, "exception", exception_gen),
        (isCriticalInitialized, "critical", critical_gen),
    ]
    search_patterns.extend(
        SearchPattern(key, needle, context_generic)
        for enabled, key, needle in optional_patterns
        if enabled
    )
    if custIsInitiated:
        search_patterns.append(SearchPattern("custom_1", cust_pattern, context_generic))
    if custIsInitiated2:
        search_patterns.append(SearchPattern("custom_2", cust_pattern2, context_generic))
    if custIsInitiated3:
        search_patterns.append(SearchPattern("custom_3", cust_pattern3, context_generic))

    analysis = analyze_lines(logoutput, search_patterns)

    def analysisValues(key, display_separator):
        result = analysis.category(key)
        return resultToDisplayRows(result, display_separator), result.match_count

    err_msg_arr, err_num = analysisValues("error_colon", display_separator)
    errgen_msg_arr, err_gen_num = analysisValues("error", display_separator_general)

    failed_msg_arr, failed_gen_num = ([], 0)
    fatalgen_msg_arr, fatal_gen_num = ([], 0)
    war_msg_arr, war_gen_num = ([], 0)
    failure_msg_arr, failure_gen_num = ([], 0)
    illegal_msg_arr, illegal_gen_num = ([], 0)
    invalid_msg_arr, invalid_gen_num = ([], 0)
    exception_msg_arr, exception_gen_num = ([], 0)
    critical_msg_arr, critical_gen_num = ([], 0)
    cust_arr, cust_arr_num = ([], 0)
    cust_arr2, cust_arr_num2 = ([], 0)
    cust_arr3, cust_arr_num3 = ([], 0)

    if isFailedInitialized:
        failed_msg_arr, failed_gen_num = analysisValues("failed", display_separator_general)
    if isFatalInitialized:
        fatalgen_msg_arr, fatal_gen_num = analysisValues("fatal", display_separator_general)
    if isWarningInitialized:
        war_msg_arr, war_gen_num = analysisValues("warning", display_separator_general)
    if isFailureInitialized:
        failure_msg_arr, failure_gen_num = analysisValues("failure", display_separator_general)
    if isIllegalInitialized:
        illegal_msg_arr, illegal_gen_num = analysisValues("illegal", display_separator_general)
    if isInvalidInitialized:
        invalid_msg_arr, invalid_gen_num = analysisValues("invalid", display_separator_general)
    if isExceptionInitialized:
        exception_msg_arr, exception_gen_num = analysisValues("exception", display_separator_general)
    if isCriticalInitialized:
        critical_msg_arr, critical_gen_num = analysisValues("critical", display_separator_general)
    if custIsInitiated:
        cust_arr, cust_arr_num = analysisValues("custom_1", display_separator_general)
    if custIsInitiated2:
        cust_arr2, cust_arr_num2 = analysisValues("custom_2", display_separator_general)
    if custIsInitiated3:
        cust_arr3, cust_arr_num3 = analysisValues("custom_3", display_separator_general)
    
    #Print results
    print("\n" + version + "\n")
    print("Filename:\n" + filename + "\n")
    print("Number of \"ERROR:\" in this file          " + str(err_num))
    print("Number of \"ERROR\" in this file           " + str(err_gen_num))
    if(isWarningInitialized):
        print("Number of \"WARNING:\" in this file        " + str(war_gen_num))
    if(isFailedInitialized):
        print("Number of \"FAILED\" in this file          " + str(failed_gen_num))
    if(isFatalInitialized):
        print("Number of \"FATAL\" in this file           " + str(fatal_gen_num))
    if(isFailureInitialized):
        print("Number of \"FAILURE\" in this file         " + str(failure_gen_num))
    if(isIllegalInitialized):
        print("Number of \"ILLEGAL\" in this file         " + str(illegal_gen_num))
    if(isInvalidInitialized):
        print("Number of \"INVALID\" in this file         " + str(invalid_gen_num))
    if(isExceptionInitialized):
        print("Number of \"EXCEPTION:\" in this file      " + str(exception_gen_num))
    if(isCriticalInitialized):
        print("Number of \"CRITICAL\" in this file        " + str(critical_gen_num))
    if custIsInitiated:
        print()
        print("Custom pattern: " + cust_pattern)
        print("Hits on pattern:                         " + str(cust_arr_num))
    if custIsInitiated2:
        print()
        print("Custom pattern: " + cust_pattern2)
        print("Hits on pattern:                         " + str(cust_arr_num2))
    if custIsInitiated3:
        print()
        print("Custom pattern: " + cust_pattern3)
        print("Hits on pattern:                         " + str(cust_arr_num3))
    print()
    print("Printed with context of:                 " + str(context))
    print("Lines in file:                           " + str(len(logoutput)))
    print()
    
    #Write to file
    if write_to_file:
        w.write("\n" + version + "\n\n")
        w.write("Filename:\n" + filename + "\n\n")
        w.write("Number of \"ERROR:\" in this file          " + str(err_num) + "\n")
        w.write("Number of \"ERROR\" in this file           " + str(err_gen_num) + "\n")
        if(isWarningInitialized):
            w.write("Number of \"WARNING:\" in this file        " + str(war_gen_num) + "\n")
        if(isFailedInitialized):
            w.write("Number of \"FAILED\" in this file          " + str(failed_gen_num) + "\n")
        if(isFatalInitialized):
            w.write("Number of \"FATAL\" in this file           " + str(fatal_gen_num) + "\n")
        if(isFailureInitialized):
            w.write("Number of \"FAILURE\" in this file         " + str(failure_gen_num) + "\n")
        if(isIllegalInitialized):
            w.write("Number of \"ILLEGAL\" in this file         " + str(illegal_gen_num) + "\n")
        if(isInvalidInitialized):
            w.write("Number of \"INVALID\" in this file         " + str(invalid_gen_num) + "\n")
        if(isExceptionInitialized):
            w.write("Number of \"EXCEPTION:\" in this file      " + str(exception_gen_num) + "\n")
        if(isCriticalInitialized):
            w.write("Number of \"CRITICAL\" in this file        " + str(critical_gen_num) + "\n")
        if custIsInitiated:
            w.write("\nCustom pattern: " + cust_pattern + "\n")
            w.write("Hits on pattern:                         " + str(cust_arr_num) + "\n")
        if custIsInitiated2:
            w.write("\nCustom pattern: " + cust_pattern2 + "\n")
            w.write("Hits on pattern:                         " + str(cust_arr_num2) + "\n")
        if custIsInitiated3:
            w.write("\nCustom pattern: " + cust_pattern3 + "\n")
            w.write("Hits on pattern:                         " + str(cust_arr_num3) + "\n")
        w.write("\n")
        w.write("Printed with context of:                 " + str(context) + "\n")
        w.write("Lines in file:                           " + str(len(logoutput)) + "\n")
        w.write("\n")

    os.system('color')
    
    generr_line = "\"ERROR:\" contained:                            |"
    printArrayResults(err_msg_arr, err_msg1, limit_output, has_limit, context, generr_line, err_num)
    if write_to_file:
        writeArrayResults(w, err_msg_arr, limit_output, has_limit, generr_line, err_msg1, err_num, context)
    
    generr_line = "\"ERROR\" contained:                             |"
    printArrayResults(errgen_msg_arr, err_gen, limit_output_gen, has_limit_gen, context_generic, generr_line, err_gen_num)
    if write_to_file:
        writeArrayResults(w, errgen_msg_arr, limit_output_gen, has_limit_gen, generr_line, err_gen, err_gen_num, context_generic)
    
    if(isFailedInitialized):
        generr_line = "\"FAILED\" contained:                            |"
        printArrayResults(failed_msg_arr, failed_gen, limit_output_failed, has_limit_failed, context_generic, generr_line, failed_gen_num)
        if write_to_file:
            writeArrayResults(w, failed_msg_arr, limit_output_failed, has_limit_failed, generr_line, failed_gen, failed_gen_num, context_generic)
    
    if(isFatalInitialized):
        generr_line = "\"FATAL\" contained:                             |"
        printArrayResults(fatalgen_msg_arr, fatal_gen, limit_output_fatal, has_limit_fatal, context_generic, generr_line, fatal_gen_num)
        if write_to_file:
            writeArrayResults(w, fatalgen_msg_arr, limit_output_fatal, has_limit_fatal, generr_line, fatal_gen, fatal_gen_num, context_generic)
        
    if(isWarningInitialized):
        generr_line = "\"WARNING:\" contained:                          |"
        printArrayResults(war_msg_arr, war_msg1, limit_output_wargen, has_limit_wargen, context_generic, generr_line, war_gen_num)
        if write_to_file:
            writeArrayResults(w, war_msg_arr, limit_output_wargen, has_limit_wargen, generr_line, war_msg1, war_gen_num, context_generic)
        
    if(isFailureInitialized):
        generr_line = "\"FAILURE\" contained:                           |"
        printArrayResults(failure_msg_arr, failure_gen, limit_output_gen, has_limit_gen, context_generic, generr_line, failure_gen_num)
        if write_to_file:
            writeArrayResults(w, failure_msg_arr, limit_output_gen, has_limit_gen, generr_line, failure_gen, failure_gen_num, context_generic)
    
    if(isIllegalInitialized):
        generr_line = "\"ILLEGAL\" contained:                           |"
        printArrayResults(illegal_msg_arr, illegal_gen, limit_output_gen, has_limit_gen, context_generic, generr_line, illegal_gen_num)
        if write_to_file:
            writeArrayResults(w, illegal_msg_arr, limit_output_gen, has_limit_gen, generr_line, illegal_gen, illegal_gen_num, context_generic)
    
    if(isInvalidInitialized):
        generr_line = "\"INVALID\" contained:                           |"
        printArrayResults(invalid_msg_arr, invalid_gen, limit_output_gen, has_limit_gen, context_generic, generr_line, invalid_gen_num)
        if write_to_file:
            writeArrayResults(w, invalid_msg_arr, limit_output_gen, has_limit_gen, generr_line, invalid_gen, invalid_gen_num, context_generic)
        
    if(isExceptionInitialized):
        generr_line = "\"EXCEPTION:\" contained:                        |"
        printArrayResults(exception_msg_arr, exception_gen, limit_output_gen, has_limit_gen, context_generic, generr_line, exception_gen_num)
        if write_to_file:
            writeArrayResults(w, exception_msg_arr, limit_output_gen, has_limit_gen, generr_line, exception_gen, exception_gen_num, context_generic)
    
    if(isCriticalInitialized):
        generr_line = "\"CRITICAL\" contained:                          |"
        printArrayResults(critical_msg_arr, critical_gen, limit_output_gen, has_limit_gen, context_generic, generr_line, critical_gen_num)
        if write_to_file:
            writeArrayResults(w, critical_msg_arr, limit_output_gen, has_limit_gen, generr_line, critical_gen, critical_gen_num, context_generic)
        
    if custIsInitiated:
        generr_line = "Pattern searched: " + cust_pattern
        printArrayResults(cust_arr, cust_pattern, limit_output_gen, has_limit_gen, context_generic, generr_line, cust_arr_num)
        if write_to_file:
            writeArrayResults(w, cust_arr, limit_output_gen, has_limit_gen, generr_line, cust_pattern, cust_arr_num, context_generic)
            
    if custIsInitiated2:
        generr_line = "Pattern searched: " + cust_pattern2
        printArrayResults(cust_arr2, cust_pattern2, limit_output_gen, has_limit_gen, context_generic, generr_line, cust_arr_num2)
        if write_to_file:
            writeArrayResults(w, cust_arr2, limit_output_gen, has_limit_gen, generr_line, cust_pattern2, cust_arr_num2, context_generic)
            
    if custIsInitiated3:
        generr_line = "Pattern searched: " + cust_pattern3
        printArrayResults(cust_arr3, cust_pattern3, limit_output_gen, has_limit_gen, context_generic, generr_line, cust_arr_num3)
        if write_to_file:
            writeArrayResults(w, cust_arr3, limit_output_gen, has_limit_gen, generr_line, cust_pattern3, cust_arr_num3, context_generic)
        
    f.close()
    if write_to_file:
        w.close()    

if __name__ == "__main__":

    toggle_btn_off = b'iVBORw0KGgoAAAANSUhEUgAAACgAAAAoCAYAAACM/rhtAAAABmJLR0QA/wD/AP+gvaeTAAAED0lEQVRYCe1WTWwbRRR+M/vnv9hO7BjHpElMKSlpqBp6gRNHxAFVcKM3qgohQSqoqhQ45YAILUUVDRxAor2VAweohMSBG5ciodJUSVqa/iikaePEP4nj2Ovdnd1l3qqJksZGXscVPaylt7Oe/d6bb9/svO8BeD8vA14GvAx4GXiiM0DqsXv3xBcJU5IO+RXpLQvs5yzTijBmhurh3cyLorBGBVokQG9qVe0HgwiXLowdy9aKsY3g8PA5xYiQEUrsk93JTtjd1x3siIZBkSWQudUK4nZO1w3QuOWXV+HuP/fL85klAJuMCUX7zPj4MW1zvC0Ej4yMp/w++K2rM9b70sHBYCjo34x9bPelsgp/XJksZ7KFuwZjr3732YcL64ttEDw6cq5bVuCvgy/sje7rT0sI8PtkSHSEIRIKgCQKOAUGM6G4VoGlwiqoVd2Za9Vl8u87bGJqpqBqZOj86eEHGNch+M7otwHJNq4NDexJD+59RiCEQG8qzslFgN8ibpvZNsBifgXmFvJg459tiOYmOElzYvr2bbmkD509e1ylGEZk1Y+Ssfan18n1p7vgqVh9cuiDxJPxKPT3dfGXcN4Tp3dsg/27hUQs0qMGpRMYjLz38dcxS7Dm3nztlUAb38p0d4JnLozPGrbFfBFm79c8hA3H2AxcXSvDz7/+XtZE1kMN23hjV7LTRnKBh9/cZnAj94mOCOD32gi2EUw4FIRUMm6LGhyiik86nO5NBdGRpxYH14bbjYfJteN/OKR7UiFZVg5T27QHYu0RBxoONV9W8KQ7QVp0iXdE8fANUGZa0QAvfhhXlkQcmjJZbt631oIBnwKmacYoEJvwiuFgWncWnXAtuVBBEAoVVXWCaQZzxmYuut68b631KmoVBEHMUUrJjQLXRAQVSxUcmrKVHfjWWjC3XOT1FW5QrWpc5IJdQhDKVzOigEqS5dKHMVplnNOqrmsXqUSkn+YzWaHE9RW1FeXL7SKZXBFUrXW6jIV6YTEvMAUu0W/G3kcxPXP5ylQZs4fa6marcWvvZfJu36kuHjlc/nMSuXz+/ejxgqPFpuQ/xVude9eu39Jxu27OLvBGoMjrUN04zrNMbgVmOBZ96iPdPZmYntH5Ls76KuxL9NyoLA/brav7n382emDfHqeooXyhQmARVhSnAwNNMx5bu3V1+habun5nWdXhwJZ2C5mirTesyUR738sv7g88UQ0rEkTDlp+1wwe8Pf0klegUenYlgyg7bby75jUTITs2rhCAXXQ2vwxz84vlB0tZ0wL4NEcLX/04OrrltG1s8aOrHhk51SaK0us+n/K2xexBxljcsm1n6x/Fuv1PCWGiKOaoQCY1Vb9gWPov50+fdEqd21ge3suAlwEvA14G/ucM/AuppqNllLGPKwAAAABJRU5ErkJggg=='
    toggle_btn_on = b'iVBORw0KGgoAAAANSUhEUgAAACgAAAAoCAYAAACM/rhtAAAABmJLR0QA/wD/AP+gvaeTAAAD+UlEQVRYCe1XzW8bVRCffbvrtbP+2NhOD7GzLm1VoZaPhvwDnKBUKlVyqAQ3/gAkDlWgPeVQEUCtEOIP4AaHSI0CqBWCQyXOdQuRaEFOk3g3IMWO46+tvZ+PeZs6apq4ipON1MNafrvreTPzfvub92bGAOEnZCBkIGQgZOClZoDrh25y5pdjruleEiX+A+rCaQo05bpuvJ/+IHJCSJtwpAHA/e269g8W5RbuzF6o7OVjF8D3Pr4tSSkyjcqfptPDMDKSleW4DKIggIAD5Yf+Oo4DNg6jbUBlvWLUNutAwZu1GnDjzrcXzGcX2AHw/emFUV6Sfk0pqcKpEydkKSo9q3tkz91uF5aWlo1Gs/mYc+i7tz4//19vsW2AU9O381TiioVCQcnlRsWeQhD3bJyH1/MiFLICyBHiuzQsD1arDvypW7DR9nzZmq47q2W95prm+I9fXfqXCX2AF2d+GhI98Y8xVX0lnxvl2UQQg0csb78ag3NjEeD8lXZ7pRTgftmCu4864OGzrq+5ZU0rCa3m+NzXlzvoAoB3+M+SyWQuaHBTEzKMq/3BMbgM+FuFCDBd9kK5XI5PJBKqLSev+POTV29lKB8rT0yMD0WjUSYLZLxzNgZvIHODOHuATP72Vwc6nQ4Uiw8MUeBU4nHS5HA6TYMEl02wPRcZBJuv+ya+UCZOIBaLwfCwQi1Mc4QXhA+PjWRkXyOgC1uIhW5Qd8yG2TK7kSweLcRGKKVnMNExWWBDTQsH9qVmtmzjiThQDs4Qz/OUSGTwcLwIQTLW58i+yOjpXDLqn1tgmDzXzRCk9eDenjo9yhvBmlizrB3V5dDrNTuY0A7opdndStqmaQLPC1WCGfShYRgHdLe32UrV3ntiH9LliuNrsToNlD4kruN8v75eafnSgC6Luo2+B3fGKskilj5muV6pNhk2Qqg5v7lZ51nBZhNBjGrbxfI1+La5t2JCzfD8RF1HTBGJXyDzs1MblONulEqPDVYXgwDIfNx91IUVbAbY837GMur+/k/XZ75UWmJ77ou5mfM1/0x7vP1ls9XQdF2z9uNsPzosXPNFA5m0/EX72TBSiqsWzN8z/GZB08pWq9VeEZ+0bjKb7RTD2i1P4u6r+bwypo5tZUumEcDAmuC3W8ezIqSGfE6g/sTd1W5p5bKjaWubrmWd29Fu9TD0GlYlmTx+8tTJoZeqYe2BZC1/JEU+wQR5TVEUPptJy3Fs+Vkzgf8lemqHumP1AnYoMZSwsVEz6o26i/G9Lgitb+ZmLu/YZtshfn5FZDPBCcJFQRQ+8ih9DctOFvdLIKHH6uUQnq9yhFu0bec7znZ+xpAGmuqef5/wd8hAyEDIQMjAETHwP7nQl2WnYk4yAAAAAElFTkSuQmCC'

    main()
