import re
import os
from termcolor import colored
import PySimpleGUI as sg

#TODO: Add custom pattern-match (Future: Add several patterns in list)
#TODO: Split printing into functions
#TODO: Fix small bug with limiter cutting off end of context
#TODO: Add context for general errors as well
#TODO: Single color of word on "Error:"-messages (And maybe color for ---> arrow)
#TODO: Expand PySimpleGui integration

#Log analysis project
def main():
    
    context = 3
    printcolor_gen = "blue"
    
    display_separator = True
    write_to_file = True
    
    limit_output = 0
    limit_output_gen = 0
    limit_output_wargen = 0
    limit_output_failed = 0
    limit_output_fatal = 0
    
    general_limit = 23
    
    version = "Logreader v0.12"
    
    #PySimpleGUI file-select
    sg.theme("SystemDefault")
    layout = [[sg.T("")], [sg.Text("Choose a logfile: "), sg.Input(key="-IN2-" ,change_submits=True), sg.FileBrowse(key="-IN-")],[sg.Button("Submit")]]
    
    window = sg.Window(version, layout, size=(600,135))
    
    while True:
        event, values = window.read()
        print(values["-IN2-"])
        if event == sg.WIN_CLOSED or event=="Exit":
            break
        elif event == "Submit":
            filename = values["-IN-"]
            break
    
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

    #Reading first, then formatting
    f = open(filename, "r")
    if write_to_file:
        w = open("outfile.txt", "w")
        
    logoutput = f.read().splitlines()

    for x in range(len(logoutput)):

        space_string = ""
        num_len = len(str(x + 1))
        
        if x >= 0:
            for z in range(7-(num_len)):
                space_string += " "
        
        logoutput[x] = str(x + 1) + space_string + "-> " + logoutput[x]

    #Types of strings we are looking for (errors, warnings, failed, fatal)
    err_msg1 = "error:"
    err_msg_arr = []

    err_gen = "error"
    errgen_msg_arr = []

    fail_gen = "failed"
    failgen_msg_arr = []

    fatal_gen = "fatal"
    fatalgen_msg_arr = []

    war_msg1 = "warning:"
    war_msg_arr = []


    #Appending the error-strings to the appropriate array, and adding context
    err_num = 0
    for x in range(len(logoutput)):

        if (err_msg1 in logoutput[x].lower()):        
            
            #Add context before the error-message
            cont_num = context
            for z in range(context):
                if (cont_num > 0):
                    if(x - cont_num) > 0:
                        if(logoutput[x - cont_num] not in err_msg_arr):
                            err_msg_arr.append(logoutput[x - cont_num])
                    cont_num += -1

            #Add the error-message
            err_msg_arr.append(logoutput[x])
            err_num +=1
            
            #Add context after the error-message
            for c in range(context):
                if((x + (c + 1)) > (len(logoutput) - 1)) or ("error:" in logoutput[x + (c + 1)].lower()):
                    break
                err_msg_arr.append(logoutput[x + (c + 1)])
            
            if display_separator:
                err_msg_arr.append(" ")
        
        #Add the generic messages
        if (war_msg1 in logoutput[x].lower()):
            war_msg_arr.append(logoutput[x])
        if (err_gen in logoutput[x].lower()) and ("error:" not in logoutput[x].lower()):
            errgen_msg_arr.append(logoutput[x])
        if (fail_gen in logoutput[x].lower()):
            failgen_msg_arr.append(logoutput[x])
        if (fatal_gen in logoutput[x].lower()):
            fatalgen_msg_arr.append(logoutput[x])

    #Checking for spaces that we dont need (places where separating errors do not make sense)        
    if display_separator:

        for x in range(len(err_msg_arr)):
            
            res = err_msg_arr[x].split()
            if not res:
                if(((x - 1) >= 0) and ((x + 1) < len(err_msg_arr))):
                    
                    #Regex to find first number in string from first element in comp.
                    #This part of the code might be unnecessarily complicated and a simple
                    #row-comparison might suffice, but it works.
                    comp1 = err_msg_arr[x - 1].split()
                    comp1_res = re.search('[0-9]+', comp1[0]).group()
                    
                    comp2 = err_msg_arr[x + 1].split()
                    comp2_res = re.search('[0-9]+', comp2[0]).group()
                    
                    if(int(comp1_res) == (int(comp2_res) - 1)):
                        err_msg_arr[x] = "remove"

        v = len(err_msg_arr) - 1
        for x in range(len(err_msg_arr)):
            
            if(err_msg_arr[v] == "remove"):
                err_msg_arr.pop(v)
            v += -1
            
        for x in range(len(err_msg_arr)):
            if(err_msg_arr[x] == " "):
                err_msg_arr[x] = "-------->"


    #Print results
    print("\n" + version + "\n")
    print("Number of errors in this file:           " + str(err_num))
    print("Number of generic errors in this file:   " + str(len(errgen_msg_arr)))
    print("Number of warnings in this file:         " + str(len(war_msg_arr)))
    print("Number of generic failures in this file: " + str(len(failgen_msg_arr)))
    print("Number of generic fatals in this file:   " + str(len(fatalgen_msg_arr)))
    print()
    print("Printed with context of:                 " + str(context))
    print("Lines in file:                           " + str(len(logoutput)))
    print()
    
    #Write to file
    if write_to_file:
        w.write("\n" + version + "\n\n")
        w.write("Number of errors in this file:           " + str(err_num) + "\n")
        w.write("Number of generic errors in this file:   " + str(len(errgen_msg_arr)) + "\n")
        w.write("Number of warnings in this file:         " + str(len(war_msg_arr)) + "\n")
        w.write("Number of generic failures in this file: " + str(len(failgen_msg_arr)) + "\n")
        w.write("Number of generic fatals in this file:   " + str(len(fatalgen_msg_arr)) + "\n")
        w.write("\n")
        w.write("Printed with context of:                 " + str(context) + "\n")
        w.write("Lines in file:                           " + str(len(logoutput)) + "\n")
        w.write("\n")

    os.system('color')

    print("------------------------------------------------")
    print("Errors contained:                              |")
    print("------------------------------------------------")
    err_count = 0
    broken = False
    for i, x in enumerate(err_msg_arr):
        if "error:" in err_msg_arr[i].lower():
            print(colored(x, 'red', attrs=["bold"]))
            err_count += 1
        else:
            print(x)
        if has_limit and (err_count == limit_output):
            print("\nLimited, showing " + str(limit_output) + " out of " + str(err_num) + " elements.")
            broken = True
            break
    if not broken:
        print("\nPrinted all " + str(err_num) + " elements.")
    
    err_count = 0
    broken = False
    if write_to_file:
        w.write("------------------------------------------------\n")
        w.write("Errors contained:                              |\n")
        w.write("------------------------------------------------\n")
        for i, x in enumerate(err_msg_arr):
            if "error:" in err_msg_arr[i].lower():
                w.write(x + "\n")
                err_count += 1
            else:
                w.write(x + "\n")
            if has_limit and (err_count == limit_output):
                w.write("\nLimited, showing " + str(limit_output) + " out of " + str(err_num) + " elements.\n")
                broken = True
                break
        if not broken:
            w.write("\nPrinted all " + str(err_num) + " elements.\n")
    print()
    print("------------------------------------------------")
    print("Generic errors contained:                      |")
    print("------------------------------------------------")
    err_count = 0
    broken = False
    for x in errgen_msg_arr:
        
        pattern = re.compile(err_gen, re.IGNORECASE)        
        warres = re.split(pattern, x, 1)
        warresword = re.findall(pattern, x)
        
        print(warres[0] + colored(warresword[0], printcolor_gen, attrs=["bold"]) + warres[1])
        
        err_count += 1
        if has_limit_gen and (err_count == limit_output_gen):
            print("\nLimited, showing " + str(limit_output_gen) + " out of " + str(len(errgen_msg_arr)) + " elements.")
            broken = True
            break
    if not broken:
        print("\nPrinted all " + str(len(errgen_msg_arr)) + " elements.")
    
    err_count = 0
    broken = False
    if write_to_file:
        w.write("\n------------------------------------------------\n")
        w.write("Generic errors contained:                      |\n")
        w.write("------------------------------------------------\n")
        for x in errgen_msg_arr:        
            w.write(x + "\n")
            
            err_count += 1
            if has_limit_gen and (err_count == limit_output_gen):
                w.write("\nLimited, showing " + str(limit_output_gen) + " out of " + str(len(errgen_msg_arr)) + " elements.\n")
                broken = True
                break
        if not broken:
            w.write("\nPrinted all " + str(len(errgen_msg_arr)) + " elements.\n")
            
    print()
    print("------------------------------------------------")
    print("Warnings contained:                            |")
    print("------------------------------------------------")
    err_count = 0
    broken = False
    for x in war_msg_arr:
        
        #Using regex to split the string apart then color the appropriate error-word
        pattern = re.compile(war_msg1, re.IGNORECASE)        
        warres = re.split(pattern, x, 1)
        warresword = re.findall(pattern, x)
        
        print(warres[0] + colored(warresword[0], printcolor_gen, attrs=["bold"]) + warres[1])
        
        err_count += 1
        if has_limit_wargen and (err_count == limit_output_wargen):
            print("\nLimited, showing " + str(limit_output_wargen) + " out of " + str(len(war_msg_arr)) + " elements.")
            broken = True
            break
    if not broken:
        print("\nPrinted all " + str(len(war_msg_arr)) + " elements.")
    
    err_count = 0
    broken = False
    if write_to_file:
        w.write("\n------------------------------------------------\n")
        w.write("Warnings contained:                            |\n")
        w.write("------------------------------------------------\n")
        for x in war_msg_arr:        
            w.write(x + "\n")
            
            err_count += 1
            if has_limit_wargen and (err_count == limit_output_wargen):
                w.write("\nLimited, showing " + str(limit_output_wargen) + " out of " + str(len(war_msg_arr)) + " elements.\n")
                broken = True
                break
    if not broken:
        w.write("\nPrinted all " + str(len(war_msg_arr)) + " elements.\n")

    print()
    print("------------------------------------------------")
    print("Generic failures contained:                    |")
    print("------------------------------------------------")
    err_count = 0
    broken = False
    for x in failgen_msg_arr:
    
        pattern = re.compile(fail_gen, re.IGNORECASE)        
        warres = re.split(pattern, x, 1)
        warresword = re.findall(pattern, x)
        
        print(warres[0] + colored(warresword[0], printcolor_gen, attrs=["bold"]) + warres[1])
        
        err_count += 1
        if has_limit_failed and (err_count == limit_output_failed):
            print("\nLimited, showing " + str(limit_output_failed) + " out of " + str(len(failgen_msg_arr)) + " elements.")
            broken = True
            break
    if not broken:
        print("\nPrinted all " + str(len(failgen_msg_arr)) + " elements.")

    err_count = 0
    broken = False
    if write_to_file:
        w.write("\n------------------------------------------------\n")
        w.write("Generic failures contained:                    |\n")
        w.write("------------------------------------------------\n")
        for x in failgen_msg_arr:        
            w.write(x + "\n")
            
            err_count += 1
            if has_limit_failed and (err_count == limit_output_failed):
                w.write("\nLimited, showing " + str(limit_output_failed) + " out of " + str(len(failgen_msg_arr)) + " elements.\n")
                broken = True
                break
    if not broken:
        w.write("\nPrinted all " + str(len(failgen_msg_arr)) + " elements.\n")

    print()
    print("------------------------------------------------")
    print("Generic fatals contained:                      |")
    print("------------------------------------------------")
    err_count = 0
    broken = False
    for x in fatalgen_msg_arr:
        
        pattern = re.compile(fatal_gen, re.IGNORECASE)        
        warres = re.split(pattern, x, 1)
        warresword = re.findall(pattern, x)
        
        print(warres[0] + colored(warresword[0], printcolor_gen, attrs=["bold"]) + warres[1])
        
        err_count += 1
        if has_limit_fatal and (err_count == limit_output_fatal):
            print("\nLimited, showing " + str(limit_output_fatal) + " out of " + str(len(fatalgen_msg_arr)) + " elements.")
            broken = True
            break
    if not broken:
        print("\nPrinted all " + str(len(fatalgen_msg_arr)) + " elements.")

    err_count = 0
    broken = False
    if write_to_file:
        w.write("\n------------------------------------------------\n")
        w.write("Generic fatals contained:                      |\n")
        w.write("------------------------------------------------\n")
        for x in fatalgen_msg_arr:        
            w.write(x + "\n")
            
            err_count += 1
            if has_limit_fatal and (err_count == limit_output_fatal):
                w.write("\nLimited, showing " + str(limit_output_fatal) + " out of " + str(len(fatalgen_msg_arr)) + " elements.")
                broken = True
                break
        if not broken:
            w.write("\nPrinted all " + str(len(fatalgen_msg_arr)) + " elements.")


    f.close()
    if write_to_file:
        w.close()
    

if __name__ == "__main__":
    main()